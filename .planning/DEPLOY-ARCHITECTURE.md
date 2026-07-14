# Deployment Architecture — Decision Record

> **v3 (2026-07-14) supersedes v2.** The data layer moved off git and onto
> Supabase. v2 is preserved below, unedited, because its findings about Pages
> build types are still true and still worth not relearning.

---

# v3 — Supabase data layer (2026-07-14, CURRENT)

## Why v2 had to go

v2 got the deploy mechanics right but kept the fatal premise: **git as the data
transport.** The collector pushed `docs/data/` every 2 minutes — ~720 commits/day,
888 in the repo by the time we stopped. GitHub's ToS treats automated
high-frequency pushing as abuse, and the account was the thing at risk. No amount
of build-quota tuning fixes that; the pushing itself was the problem.

## What changed

```
8 proxies ──► updater.py ──► SQLite (data/playlist.db — still source of truth)
                   │
                   ├─► each new track ──────► Supabase Postgres  (tracks)
                   │
                   └─► generate_data.py ──► site-data/ (gitignored)
                                │
                                └─► publish.py ──► Supabase Storage (public bucket)
                                                        │
                                                        ▼  browser fetches directly
                       GitHub Pages ──► docs/index.html (static frontend only)
```

**The collector no longer runs git at all.** `git_commit_and_push()` is deleted,
`GIT_AUTO_PUSH` is gone, `GIT_TOKEN` is gone, and the stale `scripts/deploy.sh`
(which had its own `git add -A && git push`) is deleted.

## Three decisions worth recording

1. **`deploy.yml` is KEPT.** It is tempting to delete it as "the automation that
   caused this". It is not — Pages is `build_type=workflow`, so that workflow *is*
   what publishes the site. Deleting it freezes the dashboard permanently. It only
   runs on push, so once the collector stopped pushing it went back to being what
   it should always have been: a deploy that fires when a human commits code.

2. **The aggregates stay precomputed files; they did NOT become table queries.**
   The obvious-sounding move — "point the frontend at the `tracks` table via
   PostgREST" — does not work. `generate_data.py` produces station×hour heatmap
   matrices, an sklearn-MDS 2-D cluster embedding, five pre-windowed leaderboards
   with previous-window deltas, and redundancy percentages. None of that is a
   query. So the aggregates are still generated locally and published as gzipped
   JSON to a public Storage bucket, at the same paths they had under `docs/data/`.
   The frontend's fetch model is unchanged; only its base URL moved.

3. **Egress had to be engineered, not assumed.** Pages served ~750 KB per tab per
   30s poll for free. Supabase's free tier does not. Measured: one new track
   invalidates ~862 KB of aggregates, which at the old fetch-everything cadence is
   ~34 MB/hour per open tab — enough to exhaust the free egress allowance in days.
   Two fixes, both measured:
   - **gzip on upload** — 5.4× smaller across the real payloads (34 → 6.3 MB/hr).
   - **content-hash manifest** — `publish.py` uploads only files whose hash moved
     and writes `manifest.json`; the page polls that (~1 KB) and refetches a file
     only when its hash changes. Verified over 7 poll cycles: `manifest.json`
     fetched 7×, every heavy file fetched exactly once.
   The old `?_=Date.now()` cache-buster was removed — it defeated the CDN and was
   the reason every poll was a full re-download.

## Secrets

| Key | Where | Notes |
|-----|-------|-------|
| `SUPABASE_SECRET_KEY` | `.env`, collector machine only | Bypasses RLS. This is what lets the daemon write and the public not. Never in `docs/`, never committed. |
| (none) | frontend | The Storage bucket is public, so reads need no key. If you find yourself pasting a key into `index.html`, stop. |

RLS: `SELECT` policies for `anon`/`authenticated` on all three tables, and
deliberately **no** write policy — `service_role` bypasses RLS, so "no policy" is
what restricts writes to the daemon.

## Supabase is best-effort; SQLite is not

Every Supabase call is wrapped and never raises. Network down → the collector
keeps writing SQLite and logs. `migrate_to_supabase.py` is an idempotent upsert on
`(station_id, shazam_key, recognized_at)`, so re-running it reconciles any gap.
Always-collecting outranks always-publishing.

## Verification

```bash
gh api /repos/brchn6/radio-playlist-dashboard/pages --jq .build_type   # "workflow" — keep deploy.yml
python scripts/migrate_to_supabase.py                                  # row counts must match SQLite
python scripts/updater.py --once && git status --porcelain             # MUST be clean: no commit, no push
curl -s "$SUPABASE_URL/storage/v1/object/public/dashboard/stats.json" | jq .updated_at
# anon key must NOT be able to write:
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$SUPABASE_URL/rest/v1/tracks" \
  -H "apikey: $ANON_KEY" -H 'Content-Type: application/json' -d '{"artist":"x","title":"y"}'   # expect 401/403
```

## Known limits (v3)

- Fixes v2's "no off-machine DB snapshot" TODO: history now lives in Postgres too.
- Fixes v2's ~3-min freshness ceiling: publish is ~30s.
- **Still open:** the collector runs under `nohup`, so it does not survive a
  reboot. systemd user units + `loginctl enable-linger` remain the fix.
- **Still open:** `non_music_log` has a toggle bug in `updater.py` (it closes the
  open interval instead of extending it on continuous silence), so its durations
  understate reality. That table is owned by a separate agent; the migration copies
  it verbatim rather than silently "fixing" someone else's data.

---

# v2 — Pages build types (2026-07-13, SUPERSEDED by v3)

> Kept for its findings on Pages build quotas, which remain accurate. The
> git-push data transport it describes is gone.

## The goal

Site always live, database always growing, zero cost, and nothing that
violates GitHub's usage rules.

## What we learned (corrections to v1 of this document)

1. **`[skip ci]` does NOT suppress branch-based ("legacy") Pages builds.**
   It only suppresses Actions workflows. While Pages was set to
   "Deploy from a branch", every 30s push still triggered a legacy build
   (~120 builds/hour).
2. **The thing that fixed the build-cancellation cascade was `.nojekyll`.**
   Without it, Jekyll processing made builds take 1–2 min so each build was
   cancelled by the next push. With it, builds took ~20s and completed.
3. **Legacy Pages builds have a documented soft limit of 10 builds/hour.**
   The "working" v1 setup was 12× over it — living on borrowed time.
4. **Actions minutes are FREE and unlimited for public repos.** v1 rejected a
   workflow-based deploy over a 2,000-min/month quota that only applies to
   private repos. This repo is public (required for free Pages anyway).
5. The `POST /pages/builds` API trigger only applies to legacy builds and is
   gone along with them.

## Current architecture

```
Collector (updater.py) polls 8 proxies every 30s → SQLite
        │  generate_data.py every 30s → docs/data/ (bounded aggregates)
        ▼
git commit+push every 2 min (PUSH_INTERVAL=4, no [skip ci])
        ▼
GitHub Actions "Deploy to Pages" (on: push, public repo → free)
  concurrency: group pages, cancel-in-progress: false
  → runs queue; GitHub keeps only the newest pending run
  → latest data always deploys, no build ever cancelled mid-flight
        ▼
brchn6.github.io — fresh within ~3 minutes
```

- Pages source is **GitHub Actions** (`build_type=workflow`), so pushes do not
  trigger legacy builds at all. No 10-builds/hour quota applies.
- ~720 commits/day at 2-min cadence (was 2,880). Aggregate JSON payloads are
  size-bounded and only `stats.json` carries a heartbeat timestamp, so git
  deltas stay small.
- `deploy.yml` also keeps `workflow_dispatch` for manual deploys.

## Tuning knobs (env vars for updater.py)

| Var | Default | Meaning |
|-----|---------|---------|
| `PUSH_EVERY_SECONDS` | 120 | minimum seconds between git pushes |
| `RETENTION_DAYS` | 45 | DB retention window |
| `CLEANUP_INTERVAL` | 720 | cleanup every N cycles (6h) |

## Verification

```bash
gh run list --workflow "Deploy to Pages" --limit 5   # should be green
gh api /repos/brchn6/radio-playlist-dashboard/pages --jq .build_type  # "workflow"
curl -s https://brchn6.github.io/radio-playlist-dashboard/data/stats.json | jq .updated_at
```

## Known limits

- Sub-minute freshness for public visitors is not achievable on a static host;
  ~2–3 min is the designed steady state. The "Now Playing" tab reads local
  proxies directly and is 30s-fresh on the collector machine.
- The SQLite DB lives only on the collector machine (docs/data JSON in git is
  a lossy backup). A periodic DB snapshot elsewhere is still TODO.
