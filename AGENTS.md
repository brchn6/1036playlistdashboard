# Radio Playlist Dashboard — Agent Handoff

## 🚫 ABSOLUTE RULE: NEVER DELETE USER DATA
**Never run DELETE, DROP, TRUNCATE, or any destructive operation on the
database without explicit user confirmation. This rule is ABSOLUTE.**

## ⚠️ REPEAT-DATA EPOCH — read before touching any repetition metric

`REPEAT_DATA_EPOCH = 2026-07-13T18:05:00Z` (in `scripts/generate_data.py`).

Before that moment the collector deduped each song against **all of history**,
so a song replayed later on the same station was silently dropped. Every track
older than the epoch therefore has its repeats stripped: play counts are really
"how many stations played it", not "how often".

**Any redundancy / "this station repeats itself" metric MUST filter through
`repeat_safe()` and MUST NOT be displayed until `stats.repeat_data.ready` is
true.** Publishing scores computed over pre-epoch data would mean making false
public claims about named radio stations. The numbers in
`.planning/REDUNDANCY_FEATURE.md` ("kol-hashfela 1 repeat, everyone else 0%")
are the old bug's fingerprint, not a finding — do not trust them.

## ⚠️ NEVER restart all proxies simultaneously

`proxy_manager.py restart` staggers startup now, but the underlying hazard is
permanent: N proxies starting together fire N simultaneous Shazam calls from
one IP. Shazam's response to too many calls is **not** an HTTP 429 — it simply
stops answering. On 2026-07-13 that hung all 8 proxies for 11 minutes
(`recognize()` had no timeout, so it held the lock forever) while
`proxy_manager health` still reported them "ok" — health only checks that HTTP
responds, **not** that recognition works. To tell a live proxy from a dead one,
check `/current` for `running=true` with a stale `last_started_at` and a null
`last_finished_at`.

Guards now in place: 45s recognize timeout, exponential backoff w/ jitter,
startup stagger, and `SHAZAMIO_INTERVAL=60s`. **Raise the interval before
adding stations** — it is the main lever on call volume.

## ISRC
Tracks carry an `isrc` (global recording id) from Shazam as of the epoch above;
it is the reliable key for matching to Spotify. Rows older than that have
`isrc = NULL` and **cannot be backfilled** without re-recognising.

## 🚫 THE COLLECTOR MUST NEVER PUSH TO GIT

Until 2026-07-14 the updater ran `git commit && git push` every 2 minutes —
~720 commits/day, 888 in total. That pattern risks a GitHub ToS strike and has
been **removed**. The data layer is now Supabase.

**Do not reintroduce it.** No `GIT_AUTO_PUSH`, no `git add` in a daemon, no
scripted push loop. If data needs to reach the web, it goes to Supabase.
`git push` is for source code, written by a human.

## Quick Reference

| Item | Value |
|------|-------|
| **Repo** | `brchn6/radio-playlist-dashboard` |
| **Local** | `/home/barc/dev/radio-playlist-dashboard/` |
| **Dashboard** | `https://brchn6.github.io/radio-playlist-dashboard/` |
| **Data** | Supabase — Postgres (`tracks`) + public Storage bucket (`dashboard`) |
| **Deploy** | Actions workflow on push (Pages `build_type=workflow`). Ships the **frontend only** — data no longer travels through git. Manual: `gh workflow run "Deploy to Pages"` |
| **Secrets** | `.env`: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`. Service key bypasses RLS — never put it in `docs/`. |

## Running the Services

```bash
# Start collector + all proxies
cd ~/dev/radio-playlist-dashboard
bash scripts/manage.sh start        # no GIT_AUTO_PUSH — it no longer exists

# Check everything
python scripts/proxy_manager.py health
pgrep -f updater.py

# Regenerate + publish the dashboard data by hand
python scripts/publish.py

# One-time / repair: reconcile SQLite into Supabase (idempotent upserts)
python scripts/migrate_to_supabase.py
```

## Architecture

- **8 proxies** (ports 8761-8768), one per station
- **Collector** polls all 8 every 20s → **SQLite** (`data/playlist.db`, still the
  source of truth) → mirrors each new track into **Supabase Postgres**
- **generate_data.py** builds the precomputed aggregates (heatmap matrices, MDS
  cluster embedding, windowed leaderboards, redundancy) into `site-data/`
  (gitignored). These are NOT expressible as a PostgREST query — that is why
  they stay precomputed files rather than becoming table reads.
- **publish.py** uploads only the aggregates whose content hash changed, gzipped,
  to the public Supabase Storage bucket, plus a `manifest.json` of those hashes.
- **Frontend** (`docs/index.html`) polls `manifest.json` and refetches a file only
  when its hash moves. Idle cost ~3 KB/poll instead of ~750 KB. It embeds **no
  API key** — the bucket is public.
- **Pages deploy**: `deploy.yml` on push. It serves the static frontend only.
  Keep it — it *is* the Pages deployer; deleting it takes the site down.
- **Now Playing** tab still fetches live from local proxies (30s fresh on this
  machine; fails silently and falls back to `current.json` for everyone else)
- **non_music_log** table is owned by the separate talk/ads-segment agent;
  generate_data.py reads it defensively (tolerates absence/schema change)

### Supabase is best-effort, SQLite is not

Every call into Supabase (track insert, file upload) is wrapped and **never
raises**. If Supabase is down the collector keeps writing to SQLite and logs the
failure; `migrate_to_supabase.py` is an idempotent upsert, so re-running it
backfills whatever was missed. Do not "fix" this by letting a network error
propagate — always-collecting is the whole point of the project.

## Critical Bugs Already Fixed

1. Shared temp dir → per-station `/tmp/1036-proxy-{slug}/`
2. Systemd zombie on port 8765 → disabled
3. ~~Dashboard cache buster missing `?`~~ — **obsolete.** The cache-buster is gone
   entirely: it forced a full ~750 KB re-download every 30s, which is affordable on
   Pages but not on Supabase egress. Files are now revalidated by ETag and gated on
   a content-hash manifest. Do not add one back.
4. DOM IDs corrupted by text replacement
5. Scatter Y-axis flat → station categories
6. Pages build collisions → manual deploy only
7. ~~Collector not pushing → needs `GIT_AUTO_PUSH=1`~~ — **obsolete and now harmful.**
   The collector must never push. See the rule at the top of this file.
8. ~~**Pages auto-build collapsing**~~ — **moot as of v3.** The whole class of problem
   (every-30s pushes triggering Pages builds) is gone, because the collector no longer
   pushes at all. `deploy.yml` now fires only on real code commits. The v2 record is
   kept in `.planning/DEPLOY-ARCHITECTURE.md` for history.

## Memory File
Full project memory at `~/.memory/radio-playlist-dashboard.md` — **READ BEFORE making any changes**.

## Deployment Architecture Decisions
Full analysis, failed attempts, and final solution documented in `.planning/DEPLOY-ARCHITECTURE.md` — read this before making any changes to the deploy pipeline.

## Spotify Export Feature
Planned feature to export station track history to Spotify playlists. Full planning session at `.planning/SPOTIFY-EXPORT.md` — covers 4 phases from basic "Open in Spotify" links to full API playlist creation.
