#!/usr/bin/env python3
"""
Generate static JSON data files from SQLite for GitHub Pages.

Reads the SQLite database and writes pre-computed JSON files to docs/data/.
Run this after updater.py to keep GitHub Pages in sync.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import PlaylistDB

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "docs" / "data"
DB_PATH = PROJECT_ROOT / "data" / "playlist.db"

# How many entries for each view
HISTORY_LIMIT = 500
HYPE_LIMIT = 50
SCATTER_LIMIT = 2000


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_json(obj: Any) -> Any:
    """Ensure all values are JSON-serializable."""
    if isinstance(obj, dict):
        return {k: safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [safe_json(v) for v in obj]
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    return str(obj)


def generate_all(output_dir: Path = DATA_DIR) -> dict[str, int]:
    """Generate all JSON data files. Returns file sizes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    db = PlaylistDB(DB_PATH)
    stats = db.get_stats()

    sizes = {}

    # ── current.json ──
    latest = db.get_latest_track()
    current_data = safe_json(latest) if latest else None
    (output_dir / "current.json").write_text(
        json.dumps(current_data, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    sizes["current.json"] = (output_dir / "current.json").stat().st_size

    # ── history.json ──
    history = safe_json(db.get_history(limit=HISTORY_LIMIT))
    history_data = {
        "history": history,
        "total": stats["total_tracks"],
        "returned": len(history),
        "updated_at": now_iso(),
    }
    (output_dir / "history.json").write_text(
        json.dumps(history_data, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    sizes["history.json"] = (output_dir / "history.json").stat().st_size

    # ── hype.json ──
    hype = safe_json(db.get_hype_tracks(limit=HYPE_LIMIT))
    hype_data = {
        "tracks": hype,
        "updated_at": now_iso(),
    }
    (output_dir / "hype.json").write_text(
        json.dumps(hype_data, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    sizes["hype.json"] = (output_dir / "hype.json").stat().st_size

    # ── scatter.json ──
    scatter_raw = db.get_scatter_data()
    # Limit and structure for plotting
    scatter = safe_json(scatter_raw[-SCATTER_LIMIT:]) if scatter_raw else []
    scatter_data = {
        "points": scatter,
        "total": len(scatter_raw),
        "returned": len(scatter),
        "updated_at": now_iso(),
    }
    (output_dir / "scatter.json").write_text(
        json.dumps(scatter_data, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    sizes["scatter.json"] = (output_dir / "scatter.json").stat().st_size

    # ── stats.json ──
    counts_by_date = safe_json(db.get_track_count_by_date())
    stats_data = safe_json(stats)
    stats_data["tracks_by_date"] = counts_by_date
    stats_data["updated_at"] = now_iso()
    (output_dir / "stats.json").write_text(
        json.dumps(stats_data, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    sizes["stats.json"] = (output_dir / "stats.json").stat().st_size

    db.close()
    return sizes


def main() -> None:
    sizes = generate_all()
    total = sum(sizes.values())
    print(
        json.dumps(
            {
                "event": "data_generated",
                "files": sizes,
                "total_bytes": total,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
