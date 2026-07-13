# Radio Playlist Dashboard — Agent Handoff

## 🚫 ABSOLUTE RULE: NEVER DELETE USER DATA
**Never run DELETE, DROP, TRUNCATE, or any destructive operation on the
database without explicit user confirmation. This rule is ABSOLUTE.**

## Quick Reference

| Item | Value |
|------|-------|
| **Repo** | `brchn6/radio-playlist-dashboard` |
| **Local** | `/home/barc/dev/radio-playlist-dashboard/` |
| **Dashboard** | `https://brchn6.github.io/radio-playlist-dashboard/` |
| **Deploy** | Actions workflow on every push (Pages `build_type=workflow`). Manual: `gh workflow run "Deploy to Pages"` |

## Running the Services

```bash
# Start collector + all proxies
cd ~/dev/radio-playlist-dashboard
GIT_AUTO_PUSH=1 nohup python scripts/updater.py > logs/updater.log 2>&1 &
python scripts/proxy_manager.py start

# Check everything
python scripts/proxy_manager.py health
pgrep -f updater.py

# Deploy dashboard to Pages
gh workflow run "Deploy to Pages" --repo brchn6/radio-playlist-dashboard
```

## Architecture

- **8 proxies** (ports 8761-8768), one per station
- **Collector** polls all 8 every 30s → SQLite
- **Git pusher** commits+pushes at most every 2 min (`PUSH_EVERY_SECONDS=120`, no `[skip ci]`)
- **Data files** in `docs/data/` — precomputed bounded aggregates
  (top.json, timeline.json, heatmap.json, trends.json, non_music.json, capped history.json)
- **Pages deploy**: `deploy.yml` runs on every push; concurrency queue
  (`cancel-in-progress: false`) so the newest data always deploys; repo is
  public so Actions minutes are free and unlimited
- **Now Playing** tab fetches live from local proxies (30s fresh on this machine)
- **Other tabs** load deployed Pages JSON (fresh within ~3 min)
- **non_music_log** table is owned by the separate talk/ads-segment agent;
  generate_data.py reads it defensively (tolerates absence/schema change)

## Critical Bugs Already Fixed

1. Shared temp dir → per-station `/tmp/1036-proxy-{slug}/`
2. Systemd zombie on port 8765 → disabled
3. Dashboard cache buster missing `?`
4. DOM IDs corrupted by text replacement
5. Scatter Y-axis flat → station categories
6. Pages build collisions → manual deploy only
7. Collector not pushing → needs `GIT_AUTO_PUSH=1`
8. **Pages auto-build collapsing** — Every 30s push triggered a legacy Pages build that canceled the previous one. **Final fix (v2):** Pages switched to Actions-based deploys (`build_type=workflow`) with a non-cancelling concurrency queue, pushes batched to every 2 min. Note: `[skip ci]` never suppressed legacy builds, and legacy builds have a 10/hour soft quota — see `.planning/DEPLOY-ARCHITECTURE.md` for the full corrected record.

## Memory File
Full project memory at `~/.memory/radio-playlist-dashboard.md` — **READ BEFORE making any changes**.

## Deployment Architecture Decisions
Full analysis, failed attempts, and final solution documented in `.planning/DEPLOY-ARCHITECTURE.md` — read this before making any changes to the deploy pipeline.

## Spotify Export Feature
Planned feature to export station track history to Spotify playlists. Full planning session at `.planning/SPOTIFY-EXPORT.md` — covers 4 phases from basic "Open in Spotify" links to full API playlist creation.
