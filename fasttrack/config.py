from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _frozen_layout() -> tuple[Path | None, Path | None]:
    """(writable app dir, read-only bundled resources) when running as an exe; (None, None) in source runs."""
    if not getattr(sys, "frozen", False):
        return None, None
    app_dir = Path(sys.executable).resolve().parent
    resource_dir = Path(getattr(sys, "_MEIPASS", app_dir / "_internal"))
    return app_dir, resource_dir


_APP_DIR, _RESOURCE_DIR = _frozen_layout()
FROZEN = _APP_DIR is not None
if FROZEN:
    APP_DIR = _APP_DIR
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    _RESOURCE_DIR = APP_DIR
DEFAULT_CONFIG = APP_DIR / "config.json"  # legacy location, auto-migrated into templates/
STATE_FILE = APP_DIR / "fasttrack_state.json"
TEMPLATES_DIR = APP_DIR / "templates"


def load_config(path: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    config_path = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    validate_config(data)
    return data, config_path


def save_config(data: dict[str, Any], path: str | Path) -> None:
    validate_config(data)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp.replace(target)


def load_state(path: str | Path | None = None) -> dict[str, Any]:
    """Load small UI state (e.g. the last used source folder); missing or broken files read as empty."""
    state_path = Path(path) if path else STATE_FILE
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(data: dict[str, Any], path: str | Path | None = None) -> None:
    state_path = Path(path) if path else STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp = state_path.with_suffix(state_path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp.replace(state_path)


def validate_config(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")
    canvas = data.get("canvas", {})
    width = int(canvas.get("width", 1080))
    height = int(canvas.get("height", 1920))
    fps = int(canvas.get("fps", 60))
    if width < 180 or height < 320 or width > 7680 or height > 7680:
        raise ValueError("Canvas dimensions must be between 180 and 7680 pixels")
    if width % 2 or height % 2:
        raise ValueError("Canvas width and height must be even for H.264 4:2:0 output")
    if fps < 1 or fps > 120:
        raise ValueError("FPS must be between 1 and 120")
    layers = data.get("layers")
    if not isinstance(layers, dict) or "background" not in layers:
        raise ValueError("Config must contain a layers.background entry")
    for name, layer in layers.items():
        rect = layer.get("rect", [0, 0, 1, 1])
        if len(rect) != 4 or not all(isinstance(v, (int, float)) for v in rect):
            raise ValueError(f"Layer '{name}' rect must be [x, y, width, height]")
        if rect[2] <= 0 or rect[3] <= 0:
            raise ValueError(f"Layer '{name}' width and height must be positive")
        if layer.get("kind") == "video":
            crop = layer.get("crop", [0, 0, 1, 1])
            if len(crop) != 4:
                raise ValueError(f"Layer '{name}' crop must be [x, y, width, height]")
            if crop[2] <= 0 or crop[3] <= 0:
                raise ValueError(f"Layer '{name}' crop width and height must be positive")


def template_path(game: str) -> Path:
    """Path of a game template: templates/<game>.json."""
    return TEMPLATES_DIR / f"{game.lower()}.json"


def available_templates() -> list[tuple[str, str]]:
    """(game_id, display name) for every template in templates/, sorted by name."""
    if not TEMPLATES_DIR.is_dir():
        return []
    templates: list[tuple[str, str]] = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(data.get("name") or path.stem.replace("_", " ").title())
        templates.append((path.stem.lower(), name))
    return sorted(templates, key=lambda pair: pair[1].lower())


def migrate_legacy_config() -> None:
    """Move a legacy root config.json into templates/valorant.json.

    The pre-templates build shipped exactly one game (Valorant), so a stray root
    config.json can only be a Valorant layout. Runs on GUI startup; a no-op when
    the legacy file is absent or already migrated.
    """
    if not DEFAULT_CONFIG.is_file():
        return
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    target = template_path("valorant")
    if not target.is_file():
        data = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        data.setdefault("name", "Valorant")
        save_config(data, target)
    DEFAULT_CONFIG.unlink()


def ensure_bundled_templates() -> None:
    """First run of a frozen build: copy the bundled game templates next to the exe.

    Templates must live beside FasTrack.exe because they are user-editable (the
    editor saves into them and new games are added by dropping files there);
    the copies inside the executable bundle are only a starting point.
    """
    if not FROZEN:
        return
    bundled = _RESOURCE_DIR / "templates"
    if bundled.is_dir() and not TEMPLATES_DIR.is_dir():
        shutil.copytree(bundled, TEMPLATES_DIR)


def resolve_asset(config_path: Path, asset_path: str | Path) -> Path:
    path = Path(asset_path).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def contain_fit(native_w: float, native_h: float, box_w: float, box_h: float) -> tuple[int, int]:
    """Largest size that fits inside the box while keeping the native aspect ratio."""
    if native_w <= 0 or native_h <= 0 or box_w <= 0 or box_h <= 0:
        return max(2, int(round(box_w))), max(2, int(round(box_h)))
    scale = min(box_w / native_w, box_h / native_h)
    return max(2, int(round(native_w * scale))), max(2, int(round(native_h * scale)))


def image_content_info(path: Path) -> tuple[int, int, tuple[int, int, int, int] | None]:
    """Return (width, height, alpha bounding box) for an image.

    The bounding box is None when every pixel is transparent. When it covers the
    whole image there is no transparent padding to trim.
    """
    from PIL import Image  # Deferred so config stays importable without Pillow.

    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        size = rgba.size
        bbox = rgba.getchannel("A").getbbox()
    return int(size[0]), int(size[1]), bbox


def clone_config(data: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(data)
