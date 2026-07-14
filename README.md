# 🎧 Radio Playlist Dashboard

> **Live at → [brchn6.github.io/radio-playlist-dashboard](https://brchn6.github.io/radio-playlist-dashboard/)**

A live dashboard that recognizes and logs every song playing on Israeli radio — in real time, zero cost, fully automatic.

![Dashboard demo](docs/demo.png)

---

## ✨ What it does

8 radio stations. 8 Shazam proxies. One SQLite database. A GitHub Pages dashboard that stays fresh within 3 minutes — all running on a machine at home, costing **exactly $0/month**.

| 🇮🇱 Stations | 🎵 Songs logged | ⏱️ Dashboard refresh | 💸 Monthly cost |
|---|---|---|---|
| קול השפלה, גלגלצ, 99FM, רדיו תל אביב, כאן 88, כאן ב, קול הגליל, רדיו דרום | Every recognized track | ~3 min (GitHub Pages) | **$0** |

## 🚀 Quick start

```bash
git clone https://github.com/brchn6/radio-playlist-dashboard.git
cd radio-playlist-dashboard
cp .env.example .env   # add GIT_TOKEN for auto-push
pip install -r requirements.txt
bash scripts/manage.sh start
```

That's it. Proxies spin up, the daemon starts polling, data flows to GitHub Pages.

## 🏗️ Architecture at a glance

```
8× ShazamIO proxies (ports 8761-8768, one per station)
        │
        ▼  polled every 20s
updater.py ──► SQLite ──► generate_data.py ──► docs/data/*.json
        │                                              │
        └── git push (every 2 min, only docs/data/)    │
                        │                              ▼
        GitHub Actions ──► GitHub Pages (always fresh, always free)
```

The auto-push pipeline, deploy reasoning, and all tuning knobs are documented in [`.planning/DEPLOY-ARCHITECTURE.md`](.planning/DEPLOY-ARCHITECTURE.md).

## 📋 Commands

| Command | What it does |
|---------|-------------|
| `bash scripts/manage.sh start` | Start all proxies + daemon |
| `bash scripts/manage.sh stop` | Stop everything |
| `bash scripts/manage.sh status` | Health check |
| `GIT_AUTO_PUSH=1 python scripts/updater.py` | Run daemon with auto-push |
| `python scripts/generate_data.py` | Generate static JSON manually |

## 📻 Stations

| Station | Slug |
|---------|------|
| 🟢 קול השפלה 103.6FM | `kol-hashfela` |
| 🔴 גלגלצ | `galgalatz` |
| 🔵 99FM | `99fm` |
| 🟡 רדיו תל אביב 102FM | `radio-tlv` |
| 🟣 כאן 88 | `kan-88` |
| 🟠 כאן ב | `kan-bet` |
| 🟢 קול הגליל העליון | `galil` |
| 🟢 רדיו דרום 97FM | `radio-darom` |

## 📦 Project structure

```
├── docs/                  # GitHub Pages root (index.html + data/)
├── scripts/               # updater.py, generate_data.py, db.py, proxy_manager.py
├── data/                  # SQLite database (gitignored)
├── .planning/             # Architecture decisions & design notes
└── README.md
```

## 💸 Why $0?

| Instead of… | We use… | Because… |
|---|---|---|
| A cloud VPS | A machine at home | Always-on, already paid for |
| PostgreSQL | SQLite | Tiny dataset, single writer, zero config |
| A backend server | Precomputed JSON + git push | Static hosting is free, git is transport |
| A paid recognition API | [ShazamIO](https://github.com/dotX12/shazamio) | Free Python wrapper, no API key |
| A private repo | A public repo | GitHub Actions minutes are unlimited on public repos |

## 🔗 Related

- [dotX12/shazamio](https://github.com/dotX12/shazamio) — The Python Shazam wrapper that makes this possible
- [brchn6/radio-kol-hashfela](https://github.com/brchn6/radio-kol-hashfela) — Android/iOS app for Kol Hashfela

## 📝 License

Do whatever you want. Made for the love of radio.
