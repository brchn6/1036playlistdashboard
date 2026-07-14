#!/usr/bin/env python3
"""
1036 Playlist Dashboard — Multi-Station Updater Daemon.

Polls ALL ShazamIO proxy instances, stores new tracks in SQLite (tagged by
station_id), mirrors them into Supabase Postgres, and publishes the precomputed
aggregates to Supabase Storage for the dashboard to read.

This daemon does NOT touch git. It used to `git commit && git push` docs/data
every 120s — ~720 commits/day — which is what put the GitHub account at risk.
The data layer now lives in Supabase; GitHub Pages only serves the static
frontend, deployed by .github/workflows/deploy.yml on real code commits.

SQLite remains the source of truth. Supabase is a published mirror, and every
call into it is best-effort: if Supabase is down, collection continues and
`scripts/migrate_to_supabase.py` reconciles the gap afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from db import PlaylistDB, STATIONS_CONFIG, STATIONS_BY_PORT  # noqa: E402
from publish import generate_and_publish  # noqa: E402
from supabase_client import insert_track as supabase_insert_track  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "playlist.db"

# ── defaults ───────────────────────────────────────────────────────────
DEFAULT_INTERVAL = 20
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "45"))
CLEANUP_INTERVAL = int(os.environ.get("CLEANUP_INTERVAL", "720"))  # every 6h at 30s poll
# A song longer than this window would be logged twice; a replay sooner than it
# would be missed. 30 min clears the longest tracks and is well under how soon
# radio repeats a hit.
DEDUPE_WINDOW_MINUTES = int(os.environ.get("DEDUPE_WINDOW_MINUTES", "30"))

running = True


def handle_signal(signum: int, frame) -> None:
    global running
    print(f"[updater] Signal {signum}, shutting down...", flush=True)
    running = False


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── publishing ─────────────────────────────────────────────────────────

def publish() -> None:
    """Regenerate the aggregates and push the changed ones to Supabase Storage.

    Best-effort by contract: publishing is downstream of collection, so a
    Supabase or network failure logs and returns rather than killing the loop.
    publish.py only records a file's hash once its upload succeeds, so a failed
    file is simply retried on the next cycle.
    """
    try:
        generate_and_publish()
    except Exception as exc:  # noqa: BLE001 - collection must survive anything here
        print(f"[updater] publish failed (data is safe in SQLite): {exc}", flush=True)


# ── proxy polling ──────────────────────────────────────────────────────

def fetch_proxy(port: int, timeout: int = 15) -> dict[str, Any] | None:
    """Fetch /current from a single proxy by port."""
    url = f"http://127.0.0.1:{port}/current"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[updater] proxy offline port={port}: {e}", flush=True)
        return None


def extract_track(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract recognized track from proxy state."""
    if not state:
        return None
    result = state.get("last_result")
    if not result or not isinstance(result, dict):
        return None
    if not result.get("found"):
        return None
    return {
        "artist": (result.get("artist") or "").strip(),
        "title": (result.get("title") or "").strip(),
        "text": result.get("text") or "",
        "url": result.get("url") or "",
        "shazam_key": result.get("shazam_key") or "",
        "isrc": result.get("isrc") or "",
        "recognized_at": result.get("recognized_at") or now_iso(),
    }


# ── main loop ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-station updater daemon")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    db = PlaylistDB(DB_PATH)
    stations = db.get_stations()
    station_map = {s["proxy_port"]: s["id"] for s in stations}
    slug_map = {s["slug"]: s for s in STATIONS_CONFIG}

    print(json.dumps({
        "event": "updater_start",
        "stations": len(stations),
        "ports": list(station_map.keys()),
        "interval": args.interval,
    }), flush=True)

    iteration = 0

    while running:
        iteration += 1
        loop_start = time.time()

        # ── Poll each proxy ──
        for s in stations:
            port = s["proxy_port"]
            station_id = s["id"]

            proxy_state = fetch_proxy(port)
            track = extract_track(proxy_state)

            if not track:
                # No song detected — log as non-music (commercials, talk, silence)
                open_event = db.get_open_non_music_event(station_id)
                if open_event:
                    # Extend the ongoing non-music interval
                    db.end_non_music_event(station_id)
                else:
                    # Start a new non-music interval
                    db.start_non_music_event(station_id, reason="unknown")
                continue

            # Song detected — close any open non-music interval
            db.end_non_music_event(station_id)

            # Same song across consecutive samples of one play → one row.
            # The same song hours later is a genuine replay → its own row.
            if db.track_exists(
                station_id=station_id,
                shazam_key=track.get("shazam_key", ""),
                artist=track["artist"],
                title=track["title"],
                within_minutes=DEDUPE_WINDOW_MINUTES,
            ):
                continue  # still the same play

            # New track!
            print(json.dumps({
                "event": "new_track",
                "station": s["slug"],
                "artist": track["artist"],
                "title": track["title"],
                "text": track.get("text", ""),
                "port": port,
            }), flush=True)

            recognized_at = track.get("recognized_at", now_iso())

            # SQLite first — it is the source of truth and the dedupe window
            # (db.track_exists, above) reads from it.
            db.insert_track(
                station_id=station_id,
                artist=track["artist"],
                title=track["title"],
                text=track.get("text", ""),
                url=track.get("url", ""),
                shazam_key=track.get("shazam_key", ""),
                isrc=track.get("isrc", ""),
                recognized_at=recognized_at,
            )

            # Then mirror to Postgres. Best-effort: supabase_insert_track never
            # raises, so a Supabase outage cannot stop us collecting. The row is
            # already durable in SQLite, and migrate_to_supabase.py is an
            # idempotent upsert, so re-running it later fills any gap.
            supabase_insert_track({
                "station_id": station_id,
                "station_slug": s["slug"],
                "artist": track["artist"],
                "title": track["title"],
                "text": track.get("text", ""),
                "url": track.get("url", ""),
                "shazam_key": track.get("shazam_key", ""),
                "isrc": track.get("isrc") or None,
                "recognized_at": recognized_at,
            })

        # ── Regenerate + publish the aggregates ──
        # No git anywhere. publish() uploads only the files whose content hash
        # actually changed, so an idle cycle costs ~3 KB instead of 1.5 MB.
        publish()

        # ── Periodic cleanup ──
        if iteration % CLEANUP_INTERVAL == 0:
            deleted = db.cleanup_old_tracks(days=RETENTION_DAYS)
            if deleted:
                print(json.dumps({"event": "cleanup", "deleted": deleted}), flush=True)
                publish()

        if args.once:
            break

        elapsed = time.time() - loop_start
        time.sleep(max(0.5, args.interval - elapsed))

    db.close()
    print(json.dumps({"event": "updater_stopped"}), flush=True)


if __name__ == "__main__":
    main()
