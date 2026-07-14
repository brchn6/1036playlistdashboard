#!/usr/bin/env python3
"""
One-time (but safely repeatable) backfill of the local SQLite DB into Supabase.

    python scripts/migrate_to_supabase.py [--dry-run] [--batch 500]

data/playlist.db is gitignored and exists only on the collector machine, so
until this runs there is exactly one copy of the project's entire history.
Running it is also what finally closes the "no off-machine DB snapshot" TODO in
.planning/DEPLOY-ARCHITECTURE.md.

Idempotent: every write is an upsert on a natural key, so re-running it after a
Supabase outage reconciles the gap instead of duplicating history. That is what
makes it safe for the daemon to simply drop a failed insert on the floor.

Reads SQLite READ-ONLY. Per AGENTS.md's absolute rule, nothing here deletes,
drops, or mutates local data.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from supabase_client import get_client  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "playlist.db"


def to_iso(value: str | None) -> str | None:
    """Normalize SQLite's two timestamp formats into one Postgres-safe ISO string.

    The same row carries both:
      recognized_at -> "2026-07-14T12:36:47Z"   (ISO, explicit UTC)
      created_at    -> "2026-07-14 12:37:21"    (SQLite datetime('now'), no zone)

    SQLite's datetime('now') is UTC, so the naive form is tagged as UTC rather
    than guessed at.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        print(f"  ! unparseable timestamp {raw!r} — sending NULL", flush=True)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql).fetchall()]


def chunked(items: list[Any], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill SQLite -> Supabase")
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"error: {DB_PATH} not found", file=sys.stderr)
        return 1

    client = get_client()
    if client is None and not args.dry_run:
        print(
            "error: Supabase not configured. Put SUPABASE_URL and SUPABASE_SERVICE_KEY "
            "in .env (see .env.example), then re-run.",
            file=sys.stderr,
        )
        return 1

    # file:...?mode=ro — belt and braces against ever mutating the source of truth.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    stations = rows(conn, "SELECT * FROM stations ORDER BY id")
    tracks = rows(conn, "SELECT * FROM tracks ORDER BY id")
    non_music = rows(conn, "SELECT * FROM non_music_log ORDER BY id")
    slug_by_id = {s["id"]: s["slug"] for s in stations}

    print(f"SQLite: {len(stations)} stations, {len(tracks)} tracks, {len(non_music)} non-music rows")

    # ── stations ──
    # Ids are carried over verbatim so tracks.station_id keeps resolving.
    # `website` is included here even though scripts/db.py's DDL never declared
    # it — it is populated in the live DB and the dashboard renders it.
    station_payload = [
        {
            "id": s["id"],
            "slug": s["slug"],
            "name": s["name"],
            "stream_url": s["stream_url"],
            "proxy_port": s["proxy_port"],
            "color": s.get("color") or "#6ae3c1",
            "enabled": bool(s.get("enabled", 1)),
            "website": s.get("website") or "",
            "created_at": to_iso(s.get("created_at")),
        }
        for s in stations
    ]

    # ── tracks ──
    # station_slug is denormalized in (it is not a SQLite column) so public reads
    # never need a join, matching the shape the generated JSON already had.
    #
    # NOTE: no "id". Do not send one, and do not upsert on it.
    #
    # updater.py mirrors each new track into Postgres WITHOUT an id, so Postgres
    # assigns its own from its sequence — which means SQLite ids and Postgres ids
    # diverge the moment the collector runs. Upserting on id therefore tries to
    # INSERT an existing play under a fresh id and trips uq_tracks_natural_key.
    # Nothing references tracks.id, so it is not worth preserving; the natural key
    # (station_id, shazam_key, recognized_at) is the real identity of a play.
    track_payload = [
        {
            "station_id": t["station_id"],
            "station_slug": slug_by_id.get(t["station_id"], ""),
            "artist": t["artist"],
            "title": t["title"],
            "text": t.get("text") or "",
            "url": t.get("url") or "",
            "shazam_key": t.get("shazam_key") or "",
            "isrc": t.get("isrc") or None,   # NULL on the 387 pre-epoch rows; not backfillable
            "bpm": t.get("bpm"),              # NULL for pre-epoch rows; populated by new proxy
            "musical_key": t.get("musical_key"),  # same as bpm
            "song_image": None,              # nothing in the pipeline produces this yet
            "recognized_at": to_iso(t["recognized_at"]),
            "created_at": to_iso(t.get("created_at")),
        }
        for t in tracks
    ]

    # ── non_music_log ──
    # Copied verbatim, bug and all — see supabase_schema.sql. ended_at may be NULL.
    non_music_payload = [
        {
            "id": n["id"],
            "station_id": n["station_id"],
            "started_at": to_iso(n["started_at"]),
            "ended_at": to_iso(n.get("ended_at")),
            "reason": n.get("reason") or "unknown",
        }
        for n in non_music
    ]

    conn.close()

    if args.dry_run:
        print("\n--dry-run: nothing written. Sample rows:")
        for label, payload in (
            ("station", station_payload), ("track", track_payload), ("non_music", non_music_payload)
        ):
            if payload:
                print(f"  {label}: {payload[0]}")
        return 0

    # Each table gets the conflict target that is actually its identity:
    #
    #   stations       "slug"  — ids ARE preserved (tracks.station_id points at them),
    #                            but slug is what makes a station the same station.
    #   tracks         the natural key. NOT id: see the comment on track_payload —
    #                  SQLite ids and Postgres ids diverge once the collector runs,
    #                  so upserting on id resurrects plays under new ids and trips
    #                  the unique constraint.
    #   non_music_log  "id"    — updater.py does not mirror this table to Postgres,
    #                            so its ids only ever come from here and stay aligned.
    for label, table, payload, conflict in (
        ("stations", "stations", station_payload, "slug"),
        ("tracks", "tracks", track_payload, "station_id,shazam_key,recognized_at"),
        ("non_music_log", "non_music_log", non_music_payload, "id"),
    ):
        done = 0
        for batch in chunked(payload, args.batch):
            client.table(table).upsert(batch, on_conflict=conflict).execute()
            done += len(batch)
            print(f"  {label}: {done}/{len(payload)}", flush=True)
        print(f"{label}: {done} rows upserted")

    # Explicit-id inserts don't advance the identity sequence — without this the
    # daemon's next insert would collide at id=1.
    client.rpc("reset_identity_sequences").execute()
    print("identity sequences reset")

    # Verify against the source rather than trusting the writes.
    #
    # supabase < sqlite is a real failure: rows did not land.
    # supabase > sqlite is fine and expected — Postgres is the union of every host
    # that ever collected, while this SQLite file is only what THIS host saw.
    print("\nVerifying row counts in Supabase:")
    ok = True
    for table, expected in (
        ("stations", len(station_payload)),
        ("tracks", len(track_payload)),
        ("non_music_log", len(non_music_payload)),
    ):
        got = client.table(table).select("id", count="exact").limit(1).execute().count
        if got < expected:
            mark, ok = "MISSING ROWS", False
        elif got > expected:
            mark = f"ok (+{got - expected} not in this host's SQLite)"
        else:
            mark = "ok"
        print(f"  {table:<15} sqlite={expected:<6} supabase={got:<6} {mark}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
