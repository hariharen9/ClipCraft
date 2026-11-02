from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .config import contain_fit, resolve_asset


def normalized_crop(frame: np.ndarray, crop: list[float]) -> np.ndarray:
    height, width = frame.shape[:2]
    x, y, w, h = [float(v) for v in crop]
    x0 = max(0, min(width - 1, int(round(x * width))))
    y0 = max(0, min(height - 1, int(round(y * height))))
    x1 = max(x0 + 1, min(width, int(round((x + w) * width))))
    y1 = max(y0 + 1, min(height, int(round((y + h) * height))))
    return frame[y0:y1, x0:x1]


def fit_cover(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    if width <= 0 or height <= 0:
        return np.zeros((max(1, height), max(1, width), 3), dtype=np.uint8)
    src_h, src_w = frame.shape[:2]
    scale = max(width / max(src_w, 1), height / max(src_h, 1))
    resized = cv2.resize(frame, (max(1, round(src_w * scale)), max(1, round(src_h * scale))), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    y0 = max(0, (resized.shape[0] - height) // 2)
    x0 = max(0, (resized.shape[1] - width) // 2)
    return resized[y0:y0 + height, x0:x0 + width]


def fit_contain(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    src_h, src_w = frame.shape[:2]
    scale = min(width / max(src_w, 1), height / max(src_h, 1))
    rw, rh = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    resized = cv2.resize(frame, (rw, rh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x, y = (width - rw) // 2, (height - rh) // 2
    canvas[y:y + rh, x:x + rw] = resized
    return canvas


def render_background(frame: np.ndarray, width: int, height: int, config: dict[str, Any]) -> np.ndarray:
    background = config.get("background", {})
    small_w, small_h = max(2, width // 2), max(2, height // 2)
    image = fit_cover(frame, small_w, small_h)
    blur = max(1, int(background.get("blur", 22)))
    image = cv2.GaussianBlur(image, (0, 0), sigmaX=blur, sigmaY=blur)
    brightness = float(background.get("brightness", -0.08))
    saturation = float(background.get("saturation", 0.82))
    # Blend toward gray like FFmpeg's eq=saturation (chroma scaling), not channel scaling.
    gray = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    image = cv2.addWeighted(gray, 1.0 - saturation, image, saturation, 0.0)
    image = cv2.convertScaleAbs(image, alpha=1.0, beta=brightness * 255.0)
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)


def layer_preview_image(
    name: str,
    layer: dict[str, Any],
    frame: np.ndarray,
    canvas_w: int,
    canvas_h: int,
    config_path: Path,
) -> tuple[np.ndarray | None, float | None]:
    """Return (preview image, native content aspect w/h); aspect is None for video layers."""
    rect = layer.get("rect", [0, 0, 0.1, 0.1])
    target_w = max(2, int(round(float(rect[2]) * canvas_w)))
    target_h = max(2, int(round(float(rect[3]) * canvas_h)))
    kind = layer.get("kind")
    if kind == "video":
        crop = normalized_crop(frame, layer.get("crop", [0, 0, 1, 1]))
        if layer.get("fit", "cover") == "contain":
            return fit_contain(crop, target_w, target_h), None
        return fit_cover(crop, target_w, target_h), None
    if kind == "image":
        asset = resolve_asset(config_path, layer.get("asset", ""))
        if not asset.is_file():
            return None, None
        try:
            image = Image.open(asset).convert("RGBA")
            # Transparent padding must not count towards the image's placement or aspect.
            bbox = image.getchannel("A").getbbox()
            if bbox is not None and bbox != (0, 0, image.width, image.height):
                image = image.crop(bbox)
            aspect = image.width / image.height if image.height else None
            if layer.get("fit", "fill") == "contain":
                fit_w, fit_h = contain_fit(image.width, image.height, target_w, target_h)
                image = image.resize((fit_w, fit_h), Image.Resampling.LANCZOS)
            else:
                # Free transform: the picture fills its rectangle exactly, as arranged in the editor.
                image = image.resize((target_w, target_h), Image.Resampling.LANCZOS)
            return np.array(image), aspect
        except (OSError, ValueError):
            return None, None
    return None, None


def to_qimage_array(image: np.ndarray):
    # Delayed import keeps the CLI renderer usable without Qt installed.
    from PySide6.QtGui import QImage
    if image.ndim == 2:
        height, width = image.shape
        return QImage(image.data, width, height, width, QImage.Format_Grayscale8).copy()
    if image.shape[2] == 4:
        rgba = np.ascontiguousarray(image)
        height, width = rgba.shape[:2]
        return QImage(rgba.data, width, height, width * 4, QImage.Format_RGBA8888).copy()
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if image.shape[2] == 3 else image
    rgb = np.ascontiguousarray(rgb)
    height, width = rgb.shape[:2]
    return QImage(rgb.data, width, height, width * 3, QImage.Format_RGB888).copy()
