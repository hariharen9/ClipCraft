"""Silence detection for the Split & Cut studio.

Runs FFmpeg's ``silencedetect`` over the trimmed range and returns absolute
source-time regions that can be fed straight into the existing cut model
(``clipcraft.segments``). Detection is audio-only, so it is fast even on long
recordings, and it needs no new dependency beyond the FFmpeg binary the app
already requires.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Sequence

from .segments import MIN_CUT, Cut, normalize_cuts

DEFAULT_NOISE_DB = -35.0
DEFAULT_MIN_SILENCE = 0.35
DEFAULT_PADDING = 0.08

_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_DURATION_RE = re.compile(r"silence_duration:\s*(-?\d+(?:\.\d+)?)")


def parse_silencedetect(stderr: str, start_offset: float = 0.0, total: float | None = None) -> list[Cut]:
    """Turn ``silencedetect`` log lines into absolute ``(start, end)`` regions.

    A silence that begins but never ends (the clip runs out mid-silence) is
    closed at ``start_offset + total`` when the total length is known.
    """
    regions: list[Cut] = []
    pending_start: float | None = None

    for line in stderr.splitlines():
        start_match = _START_RE.search(line)
        if start_match:
            pending_start = float(start_match.group(1))
            continue
        end_match = _END_RE.search(line)
        if end_match:
            end = float(end_match.group(1))
            if pending_start is None:
                # Some builds only report silence_end with a duration.
                duration_match = _DURATION_RE.search(line)
                if duration_match:
                    pending_start = end - float(duration_match.group(1))
                else:
                    continue
            regions.append((start_offset + pending_start, start_offset + end))
            pending_start = None

    if pending_start is not None and total is not None:
        regions.append((start_offset + pending_start, start_offset + total))

    return normalize_cuts(regions)


def _shrink(regions: Sequence[Cut], padding: float) -> list[Cut]:
    """Pull each region in by ``padding`` seconds so quiet speech tails survive."""
    padded: list[Cut] = []
    for start, end in regions:
        inner = (start + padding, end - padding)
        if inner[1] - inner[0] > MIN_CUT:
            padded.append(inner)
    return normalize_cuts(padded)


def detect_silence(
    video_path: str | Path,
    start: float,
    end: float,
    *,
    noise_db: float = DEFAULT_NOISE_DB,
    min_silence: float = DEFAULT_MIN_SILENCE,
    padding: float = DEFAULT_PADDING,
    ffmpeg: str | None = None,
) -> list[Cut]:
    """Return absolute source-time silence regions inside ``[start, end]``."""
    from .renderer import find_ffmpeg

    start = max(0.0, float(start))
    end = float(end)
    if end <= start:
        return []

    ffmpeg = ffmpeg or find_ffmpeg()
    duration = end - start
    command = [
        ffmpeg, "-hide_banner", "-nostats", "-loglevel", "info",
        "-ss", f"{start:.6f}", "-t", f"{duration:.6f}",
        "-i", str(video_path), "-vn",
        "-af", f"silencedetect=noise={noise_db:.1f}dB:d={min_silence:.3f}",
        "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        message = (result.stderr or "").strip().splitlines()
        raise RuntimeError(message[-1] if message else "silencedetect failed")

    regions = parse_silencedetect(result.stderr, start_offset=start, total=duration)
    return _shrink(regions, max(0.0, float(padding)))


def total_cut_time(regions: Sequence[Cut]) -> float:
    return sum(b - a for a, b in normalize_cuts(regions))
