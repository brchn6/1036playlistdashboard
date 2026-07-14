# BPM & Key Detection — Planning Session

## 🎯 Vision

Integrate BPM (beats-per-minute, tempo) and musical key detection into the
existing radio monitoring pipeline so the dashboard can visualize tempo and
tonality patterns across stations and time windows.

Currently the ShazamIO proxy identifies songs but returns no audio features.
librosa is now installed on head1, so we can analyse the **same 15-second
audio samples** that the proxy already captures for Shazam recognition.

## Architecture

```
Proxy captures 15s audio → ffmpeg WAV
        │
        ├── Shazam recognition ──► artist, title, isrc, …
        │
        └── librosa analysis ──► BPM (float), musical_key (str)
                                   │  ~160 ms total
                                   │
                                   ▼
                          Both stored in STATE["last_result"]
                                   │
                                   ▼
                          Updater polls /current
                                   │
                                   ▼
                          SQLite tracks.bpm + tracks.musical_key
                                   │
                                   ▼
                          Supabase Postgres mirror
                                   │
                                   ▼
                          generate_data.py computes aggregates:
                            • per-station BPM distribution
                            • per-station key prevalence
                            • BPM × hour-of-day matrix
                            • key × station matrix
                            • time-window presets
                                   │
                                   ▼
                          New dashboard tab: "🎵 BPM & Key"
```

## Performance

Benchmarked on the workstation (same librosa 0.11.0, will be similar on head1):

| Step | Time | Notes |
|------|------|-------|
| Onset envelope | 13 ms | `librosa.onset.onset_strength()` |
| Fast BPM (autocorrelation) | 33 ms | `librosa.beat.tempo(onset_envelope=…)` |
| Chroma CQT | 127 ms | `librosa.feature.chroma_cqt()` |
| Krumhansl-Schmuckler key | <1 ms | numpy corrcoef across 12 rotations × 2 modes |
| **Total** | **~160 ms** | Well under the 20s poll interval |

## Implementation Phases

### Phase 1: Audio analysis module
**File:** `scripts/audio_analysis.py`

A standalone module with two public functions:

```python
def analyze(wav_path: str | Path) -> dict[str, Any]:
    """Analyse a WAV file and return BPM + key.
    
    Returns: dict with keys:
      - bpm: float (e.g. 128.0) or None on failure
      - musical_key: str (e.g. "C major", "A minor") or None on failure
    """
```

Implementation details:
- **BPM**: Onset envelope → autocorrelation tempo via `librosa.beat.tempo()`
  with `aggregate=np.median` for robustness. Falls to None if no beats detected
  (< 30 BPM).
- **Key**: Chroma CQT → Krumhansl-Schmuckler correlation against major/minor
  templates. Returns best match key name or None.
- Both wrapped in try/except so analysis failure never propagates.
- Handles: empty files, WAV parse errors, librosa errors, silence detection.

### Phase 2: Database schema migration

In `scripts/db.py` `_init_schema()`:

```sql
ALTER TABLE tracks ADD COLUMN bpm REAL;        -- nullable float
ALTER TABLE tracks ADD COLUMN musical_key TEXT; -- nullable, e.g. "C major"
```

Also add to Supabase migration (`scripts/migrate_to_supabase.py`).

### Phase 3: Proxy enhancement

In `shazamio_proxy.py`, after a successful Shazam recognition, run librosa
analysis on the WAV file and merge into `STATE["last_result"]`:

```python
if result.get("found"):
    try:
        audio = analyze(WORK_DIR / "station-sample.wav")
        if audio:
            result["bpm"] = audio["bpm"]
            result["musical_key"] = audio["musical_key"]
    except Exception:
        pass  # BPM/key are best-effort
```

Key considerations:
- Analysis runs AFTER Shazam returns, so it doesn't delay recognition.
- If analysis fails (e.g. silent sample), result stays null — the DB accepts
  NULL for both fields.
- The temp WAV file already exists (captured for Shazam), so no extra capture.
- The proxy's `recognized_at` timestamp is the Shazam time, not the analysis
  time.

### Phase 4: Updater enhancement

In `scripts/updater.py`:

1. `extract_track()` now also extracts `bpm` and `musical_key` from proxy state.
2. `db.insert_track()` updated with `bpm` and `musical_key` parameters.
3. `supabase_insert_track()` updated with same.
4. The existing dedupe check is unaffected — BPM/key are per-play metadata.

### Phase 5: Generate BPM/key aggregates

In `scripts/generate_data.py`, add:

**New file:** `bpm_key.json`
```json
{
  "stations": {
    "kol-hashfela": {
      "bpm": {
        "mean": 120.3,
        "min": 60.0,
        "max": 180.0,
        "histogram": [[60, 80, 12], [80, 100, 45], ...],
        "by_hour": [
          {"hour": 0, "mean_bpm": 118.5, "count": 24},
          {"hour": 1, "mean_bpm": 115.2, "count": 18},
          ...
        ]
      },
      "keys": {
        "C major": 45,
        "A minor": 38,
        "G major": 32,
        ...
      }
    },
    ...
  },
  "cross_station": {
    "bpm_by_key": {
      "C major": {"mean_bpm": 120.5, "count": 120},
      ...
    }
  },
  "time_windows": {
    "overnight": {"hours": [0, 1, 2, 3, 4, 5]},
    "morning": {"hours": [6, 7, 8, 9, 10, 11]},
    "afternoon": {"hours": [12, 13, 14, 15, 16, 17]},
    "evening": {"hours": [18, 19, 20, 21, 22, 23]},
    "friday_night": {"day": 5, "hours": [18, 19, 20, 21, 22, 23]},
    "saturday_morning": {"day": 6, "hours": [6, 7, 8, 9, 10, 11]}
  }
}
```

Computation approach:
- Only use tracks WHERE bpm IS NOT NULL AND musical_key IS NOT NULL.
- BPM histogram bins: 10-BPM increments (60-70, 70-80, …, 170-180).
- Key distribution: count per (key_name, station).
- BPM_by_hour: per station, per IL hour, mean BPM + track count.
- Cross-station BPM_by_key: all stations combined, avg BPM per key.
- Time windows are client-side filter presets in the dashboard.

### Phase 6: Dashboard visualization — Integrated into "📈 מגמות" (Trends) tab

Add BPM and Key visualizations as **new cards inside the existing Trends tab**,
below the current redundancy card. No new tab.

**Card: 🎵 BPM over Time — Smooth Curve**
- Line chart: X-axis = hour of day (0-23), Y-axis = average BPM
- One line per station (or single line when a station pill is selected)
- Smooth curve (Chart.js `tension: 0.4`) showing how tempo changes
  throughout the day naturally — no discrete preset buttons needed
- The curve flowing from midnight → morning → afternoon → evening → midnight
  lets the user visually pick their window: "overnight" is the dip, "morning"
  is the rise, "Friday night" is visible if filtering by day of week
- Optional overlay: light shading for night hours (20:00-06:00)

**Card: 🎹 Key Distribution — Radial/Bar**
- Circular bar chart or grouped bar showing key prevalence
- Outer ring: major keys in warm colors, inner: minor keys in cool
- Station pill filters

**Card: 🎵 BPM × Key Scatter**
- X-axis: BPM, Y-axis: key (sorted C→B, major then minor on separate bands)
- Point size = play count, color = station
- Shows clustering: dance music (high BPM, minor keys), rock (mid BPM, major)
- Interactive hover shows song examples

**Card: 📊 Station BPM Stats**
- Per-station table: mean BPM, BPM range, most common key
- Compact, fits in a single card row

### Phase 7: Backfill existing tracks

Since we don't keep the audio WAV files after analysis, we cannot retroactively
detect BPM/key for existing tracks via audio analysis.

Options for retroactive data:
1. **Spotify API lookup** — Match existing tracks via ISRC (if available) or
   artist+title search, fetch `/audio-features` for tempo + key.
   Already have `scripts/spotify_api.py` — add an `/audio-features` endpoint.
2. **Leave null** — New tracks from now on will have BPM/key. Over time (45-day
   retention) the data fills in organically.
3. **Batch re-capture** — For each existing track, seek to its `recognized_at`
   timestamp in the stream archive (if available) and re-analyse.

**Recommendation:** Start with option 2 (null for old, populate going forward),
then add option 1 (Spotify audio features) as a separate improvement pass.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| librosa crashes on bad audio | Try/except wrapping, null result |
| BPM detection unreliable for some genres | Onset autocorrelation is genre-agnostic; median aggregation filters outliers |
| Key detection ambiguous (e.g. C vs Am) | Krumhansl-Schmuckler picks best match; both share same chroma, so this is inherent |
| CPU load on head1 increases | ~160ms per analysis per 20s = <1% CPU per proxy (8 proxies = ~6% CPU extra) |
| No historical data for existing tracks | Acceptable — new data accumulates naturally with 45-day retention |
| libroa update breaks the module | Pin `librosa==0.11.0` in requirements.txt; simple API surface (2 functions) makes it easy to fix |

## Files Changed

| File | Change |
|------|--------|
| `scripts/audio_analysis.py` | **NEW** — librosa-based BPM + key extraction |
| `scripts/db.py` | Add `bpm` + `musical_key` columns in schema and insert_track() |
| `shazamio/shazamio_proxy.py` | Run audio analysis after Shazam, add to /current response |
| `scripts/updater.py` | Pass bpm/key through extract_track → insert_track → supabase_insert_track |
| `scripts/supabase_client.py` | Accept bpm/musical_key in insert_track() |
| `scripts/migrate_to_supabase.py` | Handle new columns in upsert |
| `scripts/generate_data.py` | Compute BPM/key aggregates into bpm_key.json |
| `scripts/publish.py` | Include bpm_key.json in the manifest |
| `docs/index.html` | New BPM/Key cards inside existing Trends tab (no new tab) |
| `requirements.txt` | Add librosa dependency |
| `deploy/install.sh` | Update if exists |

## Future Ideas (not in scope for this session)

- Spotify audio features integration (danceability, energy, valence alongside BPM/key)
- BPM-based auto-playlist generation ("upbeat morning mix", "chill evening")
- Key-based harmonic mixing suggestions
- BPM trend prediction (is the station gradually speeding up over the night?)
- Per-song BPM variation tracking (live versions vs studio vs remix)
