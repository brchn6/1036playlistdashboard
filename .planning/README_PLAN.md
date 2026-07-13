# README Rewrite Plan

## Goal

Make the repo presentable for public launch. Currently the README exposes internal plumbing (ports, proxy architecture) that nobody outside the project needs to see.

---

## Problems with current README

| Issue | Example | Fix |
|-------|---------|-----|
| **Exposes internal ports** | "Port 8761" table column | Remove — irrelevant to readers |
| **Exposes proxy architecture** | Diagram with 8 proxies, updater, etc. | Simplify — most people just want to see live data |
| **Too much setup detail** | 4-step setup with venv, tokens, etc. | Move to `SETUP.md` — keep README minimal |
| **No product story** | Doesn't explain *why* this exists | Lead with the redundancy mission |
| **Tables of stream URLs** | Readers don't need raw stream URLs | Remove from README (keep in code) |

---

## Proposed structure

### Top section (above the fold)

```
# 🎧 Radio Playlist Dashboard

> **Live → brchn6.github.io/radio-playlist-dashboard**

Tracks what **8 Israeli radio stations** are playing right now,
measures **playlist redundancy**, and exposes which stations
repeat songs the most.

Built because a friend complained stations play the same songs
on loop — and I wanted to prove it with data.
```

### Badges
- Live site badge
- Last updated badge
- GitHub Pages

### How it works (short, high-level)

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ 8 Radio     │ → │ Shazam      │ → │ Dashboard   │
│ Stations    │   │ Recognition │   │ on Pages    │
└─────────────┘   └─────────────┘   └─────────────┘
  Every 20s        Every 20s         Auto-updates
```

### Features
- 🎵 **Now Playing** — see what's on air in real-time
- 📊 **Redundancy scoring** (coming soon) — which stations repeat the most
- 📈 **History & trends** — track songs over time
- 🔍 **Cross-station tracking** — songs that play on multiple stations
- 🌐 **Zero-cost hosting** — fully on GitHub Pages

### Stations monitored

| Station | Listen live |
|---------|-------------|
| 🟢 קול השפלה 103FM | [1036kh.com](https://1036kh.com) |
| 🔴 גלגלצ | [glglz.co.il](https://glglz.co.il) |
| 🔵 99FM | [99fm.co.il](https://99fm.co.il) |
| 🟡 רדיו תל אביב 102FM | [102fm.co.il](https://102fm.co.il) |
| 🟣 כאן 88 | [kan.org.il](https://www.kan.org.il/radio/88.aspx) |
| 🟠 כאן ב | [kan.org.il](https://www.kan.org.il/radio/bet.aspx) |
| 🆕 קול הגליל העליון | — |
| 🆕 רדיו דרום 97FM | [radiodarom.co.il](https://www.radiodarom.co.il/) |

### Quick start (for developers who want to run their own)

```bash
git clone https://github.com/brchn6/radio-playlist-dashboard.git
cd radio-playlist-dashboard
cp .env.example .env   # add your GitHub token
bash scripts/manage.sh start
```

Full setup guide → [SETUP.md](.planning/SETUP.md)

### Tech stack

- **Recognition** — [ShazamIO](https://github.com/dotX12/shazamio) (Python)
- **Audio capture** — FFmpeg
- **Database** — SQLite
- **Hosting** — GitHub Pages (static JSON files)
- **Automation** — Python daemon + git auto-push

### Related
- [shazamio](https://github.com/dotX12/shazamio) — the Shazam API wrapper
- [fm1.co.il](https://fm1.co.il/) — radio directory (source for additional stations)

---

## Also needed

### Clean up `docs/data/stations.json`

Remove `proxy_port` from the public JSON — it's internal only.

Current:
```json
{"id": 1, "slug": "kol-hashfela", "name": "...", "stream_url": "...", "proxy_port": 8761, "color": "...", ...}
```

Should be:
```json
{"id": 1, "slug": "kol-hashfela", "name": "...", "stream_url": "...", "color": "...", ...}
```

The `proxy_port` is only used by `proxy_manager.py` internally — the public JSON doesn't need it.

### Move technical docs

Current README has:
- Full proxy architecture diagram → move to `.planning/ARCHITECTURE.md` (already exists)
- Port table → remove entirely
- Setup guide → move to `.planning/SETUP.md` (already exists)
- Commands table → move to `.planning/SETUP.md`

### Add to README

- Link to the [live dashboard](https://brchn6.github.io/radio-playlist-dashboard/)
- Screenshot of the dashboard
- "Why this exists" story
- Contribution / feedback section
