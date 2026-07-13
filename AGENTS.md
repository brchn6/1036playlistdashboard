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
| **Deploy** | Manual only — `gh workflow run "Deploy to Pages"` |

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
- **Git pusher** pushes JSON every 30s to main branch
- **Pages deploy** manual only (`.github/workflows/deploy.yml`)
- **Now Playing** tab fetches live from local proxies (30s fresh)
- **Other tabs** load from Pages JSON (deploy when wanted)

## Critical Bugs Already Fixed

1. Shared temp dir → per-station `/tmp/1036-proxy-{slug}/`
2. Systemd zombie on port 8765 → disabled
3. Dashboard cache buster missing `?`
4. DOM IDs corrupted by text replacement
5. Scatter Y-axis flat → station categories
6. Pages build collisions → manual deploy only
7. Collector not pushing → needs `GIT_AUTO_PUSH=1`

## Memory File
Full project memory at `~/.memory/radio-playlist-dashboard.md` — **READ BEFORE making any changes**.
