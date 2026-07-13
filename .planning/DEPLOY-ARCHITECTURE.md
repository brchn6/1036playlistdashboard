# Pages Deployment Architecture — Analysis & Decision Record

## The Problem

The Radio Playlist Dashboard pushes data to GitHub every 30 seconds (47 JSON files in `docs/data/`). Every push triggers a GitHub Pages build. Pages builds take ~1-2 minutes. Since pushes arrive every 30 seconds, each build gets **cancelled** by the next push before it can complete. Result: **zero successful deployments** and a stale live site.

### Why builds get cancelled

GitHub's internal `pages-build-deployment` workflow (used by both branch-based and Actions-based Pages) has concurrency control that cancels in-progress builds when a new push arrives on the same branch. This is by design — it ensures the latest commit is always what gets deployed. But when pushes are faster than builds, it means **no build ever finishes**.

### Failed attempted solutions

| Attempt | What we tried | Why it failed |
|---------|--------------|---------------|
| **Manual-only deploy** | Set `deploy.yml` to `workflow_dispatch` | Site never auto-updates — always stale |
| **Move data to `site-data/`** | Put JSON outside `docs/` so pushes don't trigger Pages | Same problem — site never auto-updates |
| **`[skip ci]` in commits** | Prevent Actions from triggering | Branch-based Pages auto-build still fires on push |
| **Branch-based Pages** | Switch to "Deploy from a branch: main/docs" | Same cancellation — Pages cancels in-progress builds on new push regardless of method |

## The Solution: API-Triggered Deploys at Fixed Interval

### How it works

```
Collector polls proxies every 30s → SQLite → generate_data.py → docs/data/ (47 JSON files)
                                                                          │
                                    ┌─────────────────────────────────────┤
                                    ▼                                     ▼
                          git push (every 30s)                  API Pages deploy (every 15 min)
                          [skip ci] in message                  POST /pages/builds
                          No Pages build triggered              Build completes fully
                                    │                                     │
                                    ▼                                     ▼
                          GitHub (main branch)                   brchn6.github.io (LIVE)
                          Data safe, backed up                   Fresh data every ~15 min
```

### Key insight

The `gh api -X POST /repos/{owner}/{repo}/pages/builds` endpoint triggers a Pages build **directly**, bypassing push-based triggers. Since we control when this call happens, we can space it far enough apart that builds complete fully (~1-2 min build time, 15 min interval = 13 min buffer).

**Bonus:** API-triggered builds do NOT consume GitHub Actions minutes — they use the branch-based build infrastructure directly.

### Code changes (in `scripts/updater.py`)

```python
# New constant
DEPLOY_INTERVAL = 30  # every 30 iterations = every 15 min at 30s poll

# New function
def deploy_pages():
    """Trigger a GitHub Pages build via the REST API."""
    subprocess.run(
        ["gh", "api", "-X", "POST",
         "/repos/brchn6/radio-playlist-dashboard/pages/builds"],
        capture_output=True, timeout=30
    )

# In main loop, after git push
if iteration % DEPLOY_INTERVAL == 0:
    deploy_pages()

# Git commits include [skip ci]
git_commit_and_push(f"auto: multi-station update [...] [skip ci]")
```

### Files modified

| File | Change |
|------|--------|
| `scripts/updater.py` | Added `deploy_pages()` function, `DEPLOY_INTERVAL` constant, periodic deploy call, `[skip ci]` in commit messages |
| `docs/.nojekyll` | Created — prevents Jekyll processing during Pages build |
| `.github/workflows/deploy.yml` | Kept as `workflow_dispatch` (manual backup) |
| GitHub repo Settings → Pages | Set to "Deploy from a branch: main, /docs" (branch-based, not Actions-based) |

### What the user sees

- **Every 30s:** Data pushed to git with `[skip ci]` — no visible change on the live site
- **Every ~15 min:** Site updates with fresh data (all tabs except "Now Playing")
- **"Now Playing" tab:** Always live — fetches from local proxies (independent of Pages)
- **No deployment failures** — builds are spaced far enough apart to complete

### Trade-offs

| Pro | Con |
|-----|-----|
| No more build cancellations | Live data is up to ~15 min stale (vs real-time in theory) |
| Zero Actions minutes consumed | Requires `gh` CLI installed on the running machine |
| Simple, predictable schedule | Still need `gh` auth token available |
| Git history still has 30s granularity | - |

### Scalability

- **DEPLOY_INTERVAL** is configurable via env var (e.g., `DEPLOY_INTERVAL=60` for every 30 min)
- Pages build time (~1-2 min) is the lower bound for deployment frequency
- 96 API calls/day is well within GitHub's rate limits (5,000/hr)

## Verification

To confirm the fix is working:

```bash
# Check updater log for deploy triggers
grep "Pages deploy" logs/updater.log

# Check Pages build status
gh api /repos/brchn6/radio-playlist-dashboard/pages/builds | jq '.[0].status'

# Check that commits have [skip ci]
git log --oneline -5

# Force a manual deploy if needed
gh workflow run "Deploy to Pages" --repo brchn6/radio-playlist-dashboard
```

## Alternatives Considered (and why they won't work)

### 1. Rate-limit git pushes (push every 3 min instead of 30s)
- **Problem:** If build takes 2 min and push interval is 3 min, there's 1 min buffer — might work
- **Downside:** 3 min push interval means 3 min data loss window instead of 30s. Higher risk.
- **Verdict:** Possible but less safe, and still at risk if builds occasionally take >3 min.

### 2. Scheduled Actions workflow (cron every 15 min)
- **Problem:** Each workflow run consumes Actions minutes
- **Cost:** ~96 runs/day × 1 min = 2,880 min/month — over GitHub Free tier (2,000 min)
- **Verdict:** Not sustainable for free accounts.

### 3. Branch-based Pages auto-build (Deploy from main/docs)
- **Problem:** Still cancels in-progress builds on new push — same as Actions-based
- **Verdict:** Doesn't solve the core issue.

### 4. Push to a separate `data` branch, Pages from `main`
- **Problem:** Two-branch complexity, Pages can't serve from multiple branches
- **Verdict:** Over-engineered for the problem.

### 5. Serve data from local HTTP server instead of Pages
- **Problem:** Only works on the user's local machine, not on GitHub Pages URL
- **Verdict:** Not a general solution.
