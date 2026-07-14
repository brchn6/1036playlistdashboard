#!/usr/bin/env python3
"""
Audio analysis module — BPM (tempo) and musical key detection.

Uses librosa to analyse WAV audio samples captured by the ShazamIO proxy.
The proxy already captures 15-second mono 16kHz WAV files for Shazam
recognition; this module re-uses the same files to extract additional
audio features.

Public API:
    analyze(wav_path) -> dict with keys:
        - bpm: float | None
        - musical_key: str | None

Both fields are nullable — analysis failure never propagates to the caller.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import librosa

logger = logging.getLogger("audio_analysis")

# ── Krumhansl-Schmuckler key profiles ─────────────────────────────────
# Standard perceptual profiles for major and minor keys (Krumhansl & Kessler, 1982).
# These represent the stability ratings of each scale degree in the context of
# a key — higher values mean the pitch class is more "central" to the key.
MAJOR_PROFILE = np.array([
    6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88,
])
MINOR_PROFILE = np.array([
    6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17,
])
KEY_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


def _detect_key(chroma_mean: np.ndarray) -> str | None:
    """Krumhansl-Schmuckler key detection from mean chroma vector.

    Correlates the chroma distribution against rotated major/minor profiles
    and picks the best match.
    """
    if chroma_mean is None or np.any(np.isnan(chroma_mean)):
        return None
    best_corr = -1.0
    best_key = None

    for i in range(12):  # rotate through all 12 pitch classes
        for profile, mode in [(MAJOR_PROFILE, "major"), (MINOR_PROFILE, "minor")]:
            rotated = np.roll(profile, i)
            corr = np.corrcoef(chroma_mean, rotated)[0, 1]
            if corr > best_corr:
                best_corr = corr
                best_key = f"{KEY_NAMES[i]} {mode}"

    # Require at least a weak positive correlation to report a key
    if best_corr < 0.1:
        return None
    return best_key


def _detect_bpm(y: np.ndarray, sr: float) -> float | None:
    """Onset-envelope-based BPM estimation.

    Uses onset strength envelope and autocorrelation-based tempo estimation.
    This is faster than full beat tracking (~33ms vs ~2200ms for 15s @ 22kHz)
    and more robust for diverse musical genres.
    """
    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
        tempi = librosa.feature.rhythm.tempo(
            onset_envelope=onset_env.flatten(),
            sr=sr,
            aggregate=np.median,
        )
        bpm = float(tempi[0]) if tempi is not None else None
        # Reject implausible BPM values
        if bpm is not None and (bpm < 30.0 or bpm > 250.0):
            return None
        return round(bpm, 1) if bpm is not None else None
    except Exception:
        return None


def _detect_key_from_audio(y: np.ndarray, sr: float) -> str | None:
    """Extract chroma features and detect musical key."""
    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = np.mean(chroma, axis=1)
        return _detect_key(chroma_mean)
    except Exception:
        return None


def analyze(wav_path: str | Path) -> dict[str, Any]:
    """Analyse a WAV file and return BPM + key.

    Args:
        wav_path: Path to a 16-bit mono WAV file. Ideally 15 seconds at
                  16000-22050 Hz (matching the proxy's capture settings).

    Returns:
        dict with keys:
            - "bpm": float (e.g. 128.0) or None if detection failed
            - "musical_key": str (e.g. "C major", "A minor") or None
    """
    result: dict[str, Any] = {"bpm": None, "musical_key": None}

    wav_path = Path(wav_path)
    if not wav_path.exists() or wav_path.stat().st_size < 1000:
        logger.debug("WAV file too small or missing: %s", wav_path)
        return result

    try:
        y, sr = librosa.load(str(wav_path), sr=None, mono=True)
    except Exception as exc:
        logger.debug("Could not load WAV %s: %s", wav_path, exc)
        return result

    if len(y) < sr:  # Less than 1 second of audio
        logger.debug("Audio too short: %d samples", len(y))
        return result

    # Normalise to [-1, 1] — librosa already does this, but be safe
    if np.max(np.abs(y)) > 0:
        y = y / np.max(np.abs(y))

    result["bpm"] = _detect_bpm(y, sr)
    result["musical_key"] = _detect_key_from_audio(y, sr)

    if result["bpm"] is not None or result["musical_key"] is not None:
        logger.debug(
            "Analysis complete: BPM=%s, key=%s for %s",
            result["bpm"], result["musical_key"], wav_path.name,
        )

    return result


def main() -> None:
    """CLI entry point for testing."""
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Analyse WAV file for BPM and key")
    ap.add_argument("wav", help="Path to WAV file")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    result = analyze(args.wav)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
