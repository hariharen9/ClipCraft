from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import contain_fit, resolve_asset

FONT_MAP: dict[str, tuple[str, str]] = {
    "Arial": ("arial.ttf", "arialbd.ttf"),
    "Impact": ("impact.ttf", "impact.ttf"),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "Trebuchet MS": ("trebuc.ttf", "trebucbd.ttf"),
    "Comic Sans MS": ("comic.ttf", "comicbd.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf"),
}


def resolve_font(family: str, size: int, bold: bool = True) -> Any:
    candidates: list[str] = []
    if family in FONT_MAP:
        regular, bold_file = FONT_MAP[family]
        candidates.append(bold_file if bold else regular)
        candidates.append(regular)
    if not family.lower().endswith((".ttf", ".otf")):
        candidates.append(f"{family}.ttf")
    else:
        candidates.append(family)
    candidates.extend(["arialbd.ttf" if bold else "arial.ttf", "arial.ttf"])
    for cand in candidates:
        try:
            return ImageFont.truetype(cand, size)
        except (OSError, ValueError):
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def render_text_image(
    text: str,
    target_w: int,
    target_h: int,
    font_family: str = "Arial",
    font_size: int = 48,
    bold: bool = True,
    color: str = "#FFFFFF",
    stroke_color: str = "#000000",
    stroke_width: int = 3,
    align: str = "center",
    canvas_w: int = 1080,
) -> np.ndarray:
    target_w = max(2, target_w)
    target_h = max(2, target_h)
    img = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    if not text:
        return np.array(img)

    scale = max(0.1, canvas_w / 1080.0)
    actual_size = max(8, int(round(font_size * scale)))
    actual_stroke = max(0, int(round(stroke_width * scale)))
    font = resolve_font(font_family, actual_size, bold)

    draw = ImageDraw.Draw(img)
    try:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=actual_stroke, align=align)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        bbox = (0, 0, target_w, target_h)
        tw, th = target_w, target_h

    if align == "left":
        x = -bbox[0] + 4
    elif align == "right":
        x = target_w - tw - bbox[0] - 4
    else:
        x = (target_w - tw) // 2 - bbox[0]

    y = (target_h - th) // 2 - bbox[1]

    draw.text(
        (x, y),
        text,
        font=font,
        fill=color,
        stroke_width=actual_stroke,
        stroke_fill=stroke_color,
        align=align,
    )
    return np.array(img)


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
    if kind == "text":
        text = str(layer.get("text", "Text Layer"))
        font_family = str(layer.get("font", "Arial"))
        font_size = int(layer.get("font_size", 48))
        bold = bool(layer.get("bold", True))
        color = str(layer.get("color", "#FFFFFF"))
        stroke_color = str(layer.get("stroke_color", "#000000"))
        stroke_width = int(layer.get("stroke_width", 3))
        align = str(layer.get("align", "center"))
        img_arr = render_text_image(
            text, target_w, target_h,
            font_family=font_family,
            font_size=font_size,
            bold=bold,
            color=color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            align=align,
            canvas_w=canvas_w,
        )
        return img_arr, None
    return None, None


def render_caption_overlay(
    cues: list[Any],
    playhead_sec: float,
    canvas_w: int,
    canvas_h: int,
    style: Any,
) -> tuple[np.ndarray | None, int, int]:
    """Renders active word-by-word highlighted caption box onto a transparent RGBA image.

    Returns:
        tuple (rgba_image, draw_x, draw_y) or (None, 0, 0)
    """
    if not cues:
        return None, 0, 0

    # Find active cue
    active_cue = None
    for cue in cues:
        if cue.start <= playhead_sec <= cue.end + 0.05:
            active_cue = cue
            break

    if not active_cue:
        return None, 0, 0

    words = getattr(active_cue, "words", [])
    if not words:
        # Fallback to single cue text
        text = active_cue.text.upper() if getattr(style, "uppercase", True) else active_cue.text
        from .captions import CaptionWord
        words = [CaptionWord(text, active_cue.start, active_cue.end)]

    # Resolve font scaled to canvas height
    base_size = getattr(style, "font_size", 56)
    font_size = max(14, int(round(base_size * (canvas_h / 1920.0))))
    font = resolve_font(getattr(style, "font_family", "Impact"), font_size, bold=True)
    base_stroke = getattr(style, "stroke_width", 8)
    stroke_w = max(1, int(round(base_stroke * (canvas_h / 1920.0))))

    # Find active word index
    active_word_idx = -1
    if getattr(style, "word_highlight", True):
        for idx, w in enumerate(words):
            if w.start <= playhead_sec <= w.end:
                active_word_idx = idx
                break
        if active_word_idx == -1:
            if playhead_sec < words[0].start:
                active_word_idx = 0
            else:
                active_word_idx = len(words) - 1

    # Measure each word
    words_data = []
    space_box = font.getbbox(" ")
    space_w = max(4, space_box[2] - space_box[0])
    total_w = 0
    max_h = 0

    for idx, w in enumerate(words):
        w_text = w.word.upper() if getattr(style, "uppercase", True) else w.word
        bbox = font.getbbox(w_text)
        w_w = max(1, bbox[2] - bbox[0])
        w_h = max(1, bbox[3] - bbox[1])
        words_data.append((w_text, w_w, w_h, idx == active_word_idx))
        total_w += w_w
        if idx > 0:
            total_w += space_w
        max_h = max(max_h, w_h)

    # Pad image canvas to avoid clipping thick outline strokes
    pad = stroke_w * 3 + 8
    img_w = total_w + pad * 2
    img_h = max_h + pad * 2

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    curr_x = pad
    curr_y = pad

    primary_color = getattr(style, "primary_color", "#FFFFFF")
    highlight_color = getattr(style, "highlight_color", "#FFE600")
    stroke_color = getattr(style, "stroke_color", "#000000")

    for w_text, w_w, w_h, is_highlight in words_data:
        fill_col = highlight_color if is_highlight else primary_color
        draw.text(
            (curr_x, curr_y),
            w_text,
            font=font,
            fill=fill_col,
            stroke_width=stroke_w,
            stroke_fill=stroke_color,
        )
        curr_x += w_w + space_w

    pos_y = getattr(style, "position_y", 0.70)
    draw_x = (canvas_w - img_w) // 2
    draw_y = int(round(canvas_h * pos_y)) - img_h // 2

    return np.array(img), draw_x, draw_y


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
