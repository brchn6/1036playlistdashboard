# Multi-Station Architecture — Plan

## Overview

Expand from a single-station tracker to a multi-station dashboard.
7 stations, each with its own ShazamIO proxy instance, all feeding
into a single SQLite DB. Dashboard shows all stations with filters,
comparisons, and per-station views.

---

## Current State

```
ShazamIO Proxy (1 instance) → Updater → SQLite (1 table: tracks) → JSON → GitHub Pages
```

## Target State

```
ShazamIO Proxy × 7 ──┐
  (ports 8761-8767)   │
                      ├──→ MultiStation Updater ──→ SQLite (stations + tracks) ──→ JSON ──→ GitHub Pages
                      │        async poll all 7             │
                      │        every 30s                    │
                      │                              station_id on every track
```

---

## Phase 1 — Database Schema

### New tables & columns

```sql
-- Stations registry
CREATE TABLE stations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,          -- "kol-hashfela", "galgalatz"
    name        TEXT NOT NULL,                 -- display name
    stream_url  TEXT NOT NULL,
    proxy_port  INTEGER NOT NULL UNIQUE,       -- 8761, 8762, ...
    color       TEXT DEFAULT '#6ae3c1',        -- dashboard color
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);

INSERT INTO stations (slug, name, stream_url, proxy_port, color) VALUES
  ('kol-hashfela', 'קול השפלה 103.6FM',  'https://radio.streamgates.net/stream/1036kh',   8761, '#6ae3c1'),
  ('galgalatz',    'גלגלצ',            'https://glzwizzlv.bynetcdn.com/glglz_mp3',       8762, '#e36a6a'),
  ('99fm',         '99FM',             'https://99.livecdn.biz/99fm_aac',                8763, '#6ab8e3'),
  ('radio-tlv',    'רדיו תל אביב 102FM','https://102.livecdn.biz/102fm_aac',             8764, '#e3c86a'),
  ('kan-88',       'כאן 88',           'https://27953.live.streamtheworld.com/KAN_88.mp3',8765, '#c86ae3'),
  ('kan-bet',      'כאן ב',            'https://27953.live.streamtheworld.com/KAN_BET.mp3',8766, '#e38a6a'),
  ('galil',        'קול הגליל העליון',  'https://radio.streamgates.net/stream/galil',     8767, '#a06ae3');

-- Add station_id to existing tracks table
ALTER TABLE tracks ADD COLUMN station_id INTEGER REFERENCES stations(id);
CREATE INDEX idx_tracks_station_id ON tracks(station_id);
```

### Migration (existing data)

- Set `station_id = 1` (kol-hashfela) for existing tracks
- No data loss

---

## Phase 2 — Multi-Proxy Infrastructure

### File: `scripts/proxy_manager.py`

```python
# Manages 7 ShazamIO proxy instances

STATIONS_CONFIG = [
    {"slug": "kol-hashfela", "port": 8761, "stream": "https://radio.streamgates.net/stream/1036kh"},
    {"slug": "galgalatz",    "port": 8762, "stream": "https://glzwizzlv.bynetcdn.com/glglz_mp3"},
    # ... all 7
]

class ProxyManager:
    def start_all(self):      # spawn 7 nohup processes
    def stop_all(self):       # kill all
    def status(self):         # check each port
    def start_one(self, slug):# single station
    def stop_one(self, slug):
    def health(self):         # returns {slug: online/offline}
```

Each proxy instance:
```
python shazamio_proxy.py --port 8761 --stream https://... --interval 60
```

### File: `scripts/updater.py` (multi-station version)

```python
# Async loop polling all 7 proxies

async def poll_all():
    while True:
        for station in stations:
            state = await fetch_proxy(f"http://localhost:{station.port}/current")
            track = extract_track(state)
            if track and is_new(track, station.id):
                db.insert_track(station_id=station.id, **track)
        generate_static_data()
        await asyncio.sleep(30)
```

### Port assignments

| Station | Port |
|---------|------|
| קול השפלה 103.6FM | 8761 |
| גלגלצ | 8762 |
| 99FM | 8763 |
| רדיו תל אביב 102FM | 8764 |
| כאן 88 | 8765 |
| כאן ב | 8766 |
| קול הגליל העליון | 8767 |

---

## Phase 3 — Static Data Generation

### File: `scripts/generate_data.py` (multi-station version)

Generate per-station and aggregated JSON:

```
docs/data/
├── stations.json          # station metadata (colors, names)
├── current.json           # all current tracks per station
├── history.json           # all tracks (with station_id filter)
├── hype.json              # most played per station + overall
├── scatter.json           # all points colored by station
├── stats.json             # per-station + total stats
└── stations/
    ├── kol-hashfela/
    │   ├── current.json
    │   ├── history.json
    │   ├── hype.json
    │   ├── scatter.json
    │   └── stats.json
    ├── galgalatz/
    │   └── ...
    └── ...
```

### Per-station data files (for lazy loading)

Each station gets its own mini JSON set so the dashboard can load data
on-demand instead of downloading everything at once.

---

## Phase 4 — Dashboard

### Multi-station UI layout

```
┌─────────────────────────────────────────────────────┐
│  🎧 1036 פלייליסט דשבורד                            │
│                                                     │
│  [🇮🇱 All] [103FM] [גלגלצ] [99FM] [102FM] [88] [ב] [גליל] │
│  ─────────────────────────────────────────────────── │
│                                                     │
│  ┌─ Current track ───────────────────────────────┐  │
│  │  Station: ● גלגלצ                               │  │
│  │  Artist:  Omer Adam                             │  │
│  │  Title:   Tel Aviv                              │  │
│  └────────────────────────────────────────────────┘  │
│                                                     │
│  [עכשיו] [היסטוריה] [לייקים] [פיזור] [סטטיסטיקה]       │
│  ─────────────────────────────────────────────────── │
│                                                     │
│  ┌─ Scatter (colored by station) ────────────────┐  │
│  │  🟢 103FM  🔴 גלגלצ  🔵 99FM  🟡 102FM       │  │
│  │  🟣 88FM   🟠 כאן ב  🆕 גליל                  │  │
│  │  [Chart.js scatter with station colors]        │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Station selector behavior

- **Click station tab** — filter all views to that station
- **"All" tab** — aggregated view across all stations
- **Color coding** — consistent color per station across all charts
- **Comparison scatter** — overlay all stations, each with unique color

### Data flow

```
┌─────────┐  fetch(stations.json)     station list
│ Dashboard│ ──────────────────────►  names, colors, ports
│ (JS)     │
│          │  fetch(data/current.json)  all current tracks
│          │  fetch(data/stats.json)    aggregated stats
│          │
│          │  fetch(stations/kol-hashfela/history.json)
│          │  fetch(stations/galgalatz/scatter.json)
│          │  ... (lazy per tab switch)
└─────────┘
```

---

## Phase 5 — Deployment & CI

### File: `scripts/manage.sh` (multi-station)

```bash
bash scripts/manage.sh start          # start all 7 proxies + updater
bash scripts/manage.sh start galgalatz# start single station
bash scripts/manage.sh stop           # stop everything
bash scripts/manage.sh status         # health check all 7
bash scripts/manage.sh logs galgalatz # tail logs for one station
```

### SystemD user services (optional)

```bash
systemctl --user enable --now shazamio@8761   # one service per port
systemctl --user enable --now shazamio@8762   # using template unit
systemctl --user enable --now shazamio@8763
...
```

### Resource estimation

| Resource | Per station | 7 stations total |
|----------|-------------|------------------|
| RAM (proxy) | ~50 MB | ~350 MB |
| RAM (updater) | — | ~50 MB |
| Disk/45 days | ~6 MB | ~42 MB |
| CPU | 1-5% | ~10-20% |
| Network | ~64 kbps | ~448 kbps |

---

## Implementation Order

```
Phase 1: DB schema (stations table, migration)
Phase 2: Multi-proxy manager (proxy_manager.py)
Phase 3: Multi-station updater (async updater.py)
Phase 4: Per-station data generation (generate_data.py)
Phase 5: Dashboard tabs + per-station views (index.html)
Phase 6: Manager script update + deployment
```

Each phase is ~1 session of work. Ready to start Phase 1 anytime.
