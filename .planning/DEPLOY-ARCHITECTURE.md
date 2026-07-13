# Pages Deployment Architecture — Decision Record (v2, 2026-07-13)

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
| `PUSH_INTERVAL` | 4 | push every N poll cycles (4 × 30s = 2 min) |
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
