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
SUPPORTED_AUDIO_EXTENSIONS: set[str] = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}

AUDIO_DEFAULTS: dict[str, Any] = {
    "bgm_volume": 0.35,
    "gameplay_volume": 1.0,
    "bgm_start": 0.0,
    "bgm_end": 0.0,
    "auto_ducking": True,
    "ducking_threshold": 0.125,
    "ducking_ratio": 4.0,
    "ducking_attack": 20.0,
    "ducking_release": 250.0,
    "fade_in": 0.5,
    "fade_out": 0.5,
}


def format_token_time(seconds: float) -> str:
    """Format seconds into concise time tokens (e.g. '0s', '15s', '1m20s')."""
    s = max(0, int(round(seconds)))
    if s >= 60:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s}s"


_format_token_time = format_token_time


def set_app_user_model_id() -> None:
    """Ensure Windows taskbar and titlebar group under ClipCraft instead of generic python."""
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("clipcraft.videoeditor.app")
        except Exception:
            pass


def get_app_icon():
    """Return the high-resolution application QIcon with robust path discovery and procedural fallback."""
    from pathlib import Path
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
    from clipcraft.config import APP_DIR, BUNDLE_DIR

    candidates = [
        APP_DIR / "clipcraft.ico",
        BUNDLE_DIR / "clipcraft.ico",
        Path(__file__).resolve().parent.parent.parent / "clipcraft.ico",
        APP_DIR / "templates" / "assets" / "valo_logo.png",
    ]
    for p in candidates:
        if p.is_file():
            ico = QIcon(str(p))
            if not ico.isNull():
                return ico

    # High-quality fallback icon
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(18, 24, 38))
    p.setPen(QColor(0, 229, 255))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor(255, 255, 255))
    f = p.font()
    f.setBold(True)
    f.setPointSize(22)
    p.setFont(f)
    p.drawText(pix.rect(), 0x0084, "CC")  # Qt.AlignmentFlag.AlignCenter
    p.end()
    return QIcon(pix)

