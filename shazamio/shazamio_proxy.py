#!/usr/bin/env python3
"""Local ShazamIO proxy and station listener for Radio Kol Hashfela."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from shazamio import Shazam

DEFAULT_STREAM_URL = "https://radio.streamgates.net/stream/1036kh"

HOST = os.environ.get("SHAZAMIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHAZAMIO_PORT", "8765"))
STREAM_URL = os.environ.get("RADIO_STREAM_URL", DEFAULT_STREAM_URL)
SAMPLE_SECONDS = int(os.environ.get("SHAZAMIO_SAMPLE_SECONDS", "15"))
INTERVAL_SECONDS = int(os.environ.get("SHAZAMIO_INTERVAL_SECONDS", "20"))
RETRY_DELAY = int(os.environ.get("SHAZAMIO_RETRY_DELAY", "5"))
WORK_DIR = Path(os.environ.get("SHAZAMIO_WORK_DIR", "/tmp/radio-kol-hashfela-shazamio"))

STATE: dict[str, Any] = {
    "running": False,
    "stream_url": STREAM_URL,
    "sample_seconds": SAMPLE_SECONDS,
    "interval_seconds": INTERVAL_SECONDS,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
    "last_result": None,
}

recognition_lock = asyncio.Lock()
shazam = Shazam()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_shazam_result(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"found": False, "raw_type": str(type(raw))}

    track = raw.get("track")
    if not isinstance(track, dict):
        return {"found": False, "raw_keys": sorted(raw.keys())}

    title = (track.get("title") or "").strip()
    artist = (track.get("subtitle") or "").strip()
    text = " — ".join(part for part in (artist, title) if part)

    return {
        "found": bool(title or artist),
        "artist": artist,
        "title": title,
        "text": text,
        "url": track.get("url"),
        "shazam_key": track.get("key"),
        "recognized_at": now_iso(),
    }


async def run_ffmpeg_capture(stream_url: str, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-t",
        str(SAMPLE_SECONDS),
        "-i",
        stream_url,
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_file),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg capture failed: "
            + (stderr.decode("utf-8", "replace") or stdout.decode("utf-8", "replace")).strip()
        )


async def recognize_file(path: Path) -> dict[str, Any]:
    async with recognition_lock:
        STATE["running"] = True
        STATE["last_started_at"] = now_iso()
        STATE["last_error"] = None
        try:
            raw = await shazam.recognize(str(path))
            result = parse_shazam_result(raw)
            STATE["last_result"] = result
            STATE["last_finished_at"] = now_iso()
            print(json.dumps({"event": "recognized", **result}, ensure_ascii=False), flush=True)
            return result
        except Exception as exc:
            STATE["last_error"] = str(exc)
            STATE["last_finished_at"] = now_iso()
            print(json.dumps({"event": "recognition_error", "error": str(exc)}, ensure_ascii=False), flush=True)
            raise
        finally:
            STATE["running"] = False


async def recognize_station_once() -> dict[str, Any]:
    sample_path = WORK_DIR / "station-sample.wav"
    await run_ffmpeg_capture(STREAM_URL, sample_path)
    return await recognize_file(sample_path)


async def station_loop(app: web.Application) -> None:
    """Main recognition loop.

    On successful recognition: sleep INTERVAL_SECONDS before next sample.
    On failure (not found or error): retry immediately after RETRY_DELAY seconds,
    so song transitions are caught quickly instead of waiting a full cycle.
    """
    await asyncio.sleep(1)
    consecutive_failures = 0
    while True:
        try:
            print(json.dumps({"event": "station_sample_start", "url": STREAM_URL}, ensure_ascii=False), flush=True)
            result = await recognize_station_once()
            if result.get("found"):
                consecutive_failures = 0
                print(json.dumps({"event": "sleep_next", "seconds": INTERVAL_SECONDS}, ensure_ascii=False), flush=True)
                await asyncio.sleep(INTERVAL_SECONDS)
            else:
                consecutive_failures += 1
                delay = min(RETRY_DELAY * consecutive_failures, 30)
                print(json.dumps({"event": "retry_soon", "reason": "not_found",
                                  "consecutive_failures": consecutive_failures,
                                  "retry_delay": delay}, ensure_ascii=False), flush=True)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            consecutive_failures += 1
            STATE["last_error"] = str(exc)
            print(json.dumps({"event": "station_sample_error", "error": str(exc),
                              "consecutive_failures": consecutive_failures}, ensure_ascii=False), flush=True)
            delay = min(RETRY_DELAY * consecutive_failures, 30)
            await asyncio.sleep(delay)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "shazamio-proxy"})


async def current(request: web.Request) -> web.Response:
    return web.json_response(STATE)


async def listen_once(request: web.Request) -> web.Response:
    try:
        result = await recognize_station_once()
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"found": False, "error": str(exc)}, status=500)


async def recognize_upload(request: web.Request) -> web.Response:
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"found": False, "error": "multipart field 'file' is required"}, status=400)

    suffix = Path(field.filename or "sample.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(prefix="shazamio-upload-", suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            tmp.write(chunk)

    try:
        result = await recognize_file(tmp_path)
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"found": False, "error": str(exc)}, status=500)
    finally:
        tmp_path.unlink(missing_ok=True)


async def on_startup(app: web.Application) -> None:
    app["station_task"] = asyncio.create_task(station_loop(app))


async def on_cleanup(app: web.Application) -> None:
    task = app.get("station_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> web.Application:
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_get("/current", current)
    app.router.add_post("/listen-once", listen_once)
    app.router.add_post("/recognize", recognize_upload)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "event": "startup",
                "host": HOST,
                "port": PORT,
                "stream_url": STREAM_URL,
                "sample_seconds": SAMPLE_SECONDS,
                "interval_seconds": INTERVAL_SECONDS,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    web.run_app(create_app(), host=HOST, port=PORT)
