from __future__ import annotations

from typing import Any

HANDLE_SIZE = 6.0
MIN_LAYER_SIZE = 10.0

BG_DEFAULTS: dict[str, float] = {
    "blur": 22.0,
    "brightness": -0.08,
    "saturation": 0.82,
}

BG_PRESETS: dict[str, dict[str, float]] = {
    "Dark Focus": {"blur": 22.0, "brightness": -0.08, "saturation": 0.82},
    "Vivid Glow": {"blur": 20.0, "brightness": -0.04, "saturation": 1.35},
    "Subtle Blur": {"blur": 8.0, "brightness": -0.05, "saturation": 1.00},
    "Original Brightness": {"blur": 22.0, "brightness": 0.00, "saturation": 1.00},
}

RENDER_PRESETS: dict[str, dict[str, Any]] = {
    "Fast Draft": {"fps": 30, "quality": 26, "encoder": "auto"},
    "Balanced": {"fps": 60, "quality": 19, "encoder": "auto"},
    "Best Quality 60fps": {"fps": 60, "quality": 14, "encoder": "nvenc"},
}

SUPPORTED_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


def format_token_time(seconds: float) -> str:
    """Format seconds into concise time tokens (e.g. '0s', '15s', '1m20s')."""
    s = max(0, int(round(seconds)))
    if s >= 60:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s}s"


_format_token_time = format_token_time
