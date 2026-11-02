from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates += [
            Path("C:/Windows/Fonts/seguisb.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        ]
    else:
        candidates += [
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_valorant_title(path: Path) -> None:
    image = Image.new("RGBA", (1200, 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    red = (255, 70, 82, 255)
    # A clean, angular V mark inspired by the red mark in the supplied layout.
    draw.polygon([(35, 28), (185, 28), (119, 154), (72, 154)], fill=red)
    draw.polygon([(197, 28), (262, 28), (262, 109), (221, 109)], fill=red)
    draw.polygon([(67, 171), (122, 171), (182, 218), (105, 218)], fill=red)
    font = _font(130, True)
    draw.text((290, 31), "VALORANT", font=font, fill=red, stroke_width=0)
    # Small TM mark.
    draw.text((1090, 151), "TM", font=_font(22, True), fill=red)
    image.save(path)


def make_socials(path: Path, youtube_handle: str, instagram_handle: str) -> None:
    image = Image.new("RGBA", (900, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    text_font = _font(49, True)
    shadow = (0, 0, 0, 150)
    # YouTube icon.
    draw.rounded_rectangle((8, 17, 82, 73), radius=18, fill=(242, 35, 45, 255))
    draw.polygon([(38, 29), (38, 61), (63, 45)], fill=(255, 255, 255, 255))
    draw.text((105, 16), youtube_handle, font=text_font, fill=shadow, stroke_width=2, stroke_fill=shadow)
    draw.text((103, 13), youtube_handle, font=text_font, fill=(255, 255, 255, 255))
    # Instagram camera mark with a compact warm-to-magenta outer gradient effect.
    draw.rounded_rectangle((12, 111, 78, 177), radius=19, fill=(225, 64, 112, 255), outline=(255, 170, 88, 255), width=4)
    draw.rounded_rectangle((25, 124, 65, 164), radius=12, outline=(255, 255, 255, 255), width=5)
    draw.ellipse((36, 135, 54, 153), outline=(255, 255, 255, 255), width=4)
    draw.ellipse((56, 126, 62, 132), fill=(255, 255, 255, 255))
    draw.text((105, 110), instagram_handle, font=text_font, fill=shadow, stroke_width=2, stroke_fill=shadow)
    draw.text((103, 107), instagram_handle, font=text_font, fill=(255, 255, 255, 255))
    image.save(path)


def make_panda_logo(path: Path, channel_name: str) -> None:
    width, height = 620, 430
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((115, 20, 505, 355), fill=(40, 255, 235, 75))
    glow = glow.filter(ImageFilter.GaussianBlur(38))
    image.alpha_composite(glow)
    draw = ImageDraw.Draw(image)
    # Panda silhouette: intentionally a replaceable starter mark, not a baked screenshot crop.
    draw.ellipse((153, 32, 280, 166), fill=(13, 17, 24, 255))
    draw.ellipse((342, 32, 469, 166), fill=(13, 17, 24, 255))
    draw.ellipse((150, 72, 474, 355), fill=(9, 15, 24, 255), outline=(22, 255, 238, 255), width=9)
    draw.ellipse((176, 93, 448, 333), fill=(247, 249, 247, 255))
    # Eye patches, eyes and nose.
    draw.ellipse((205, 164, 286, 255), fill=(6, 13, 23, 255))
    draw.ellipse((339, 164, 420, 255), fill=(6, 13, 23, 255))
    draw.ellipse((233, 193, 263, 226), fill=(245, 250, 255, 255))
    draw.ellipse((362, 193, 392, 226), fill=(245, 250, 255, 255))
    draw.ellipse((245, 204, 259, 219), fill=(4, 8, 15, 255))
    draw.ellipse((370, 204, 384, 219), fill=(4, 8, 15, 255))
    draw.ellipse((295, 250, 330, 278), fill=(10, 15, 23, 255))
    draw.arc((278, 258, 348, 310), start=15, end=165, fill=(10, 15, 23, 255), width=6)
    name_font = _font(62, True)
    bbox = draw.textbbox((0, 0), channel_name, font=name_font, stroke_width=1)
    text_w = bbox[2] - bbox[0]
    draw.text(((width - text_w) / 2, 348), channel_name, font=name_font,
              fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(24, 50, 65, 220))
    image.save(path)


def ensure_assets(config: dict, config_path: Path) -> dict[str, Path]:
    """Create the default editable branding PNGs if the configured paths are the defaults."""
    branding = config.get("branding", {})
    output: dict[str, Path] = {}
    defaults = {
        "valorant_title": ("assets/valorant_title.png", lambda p: make_valorant_title(p)),
        "socials": ("assets/socials.png", lambda p: make_socials(
            p, str(branding.get("youtube_handle", "@youryoutube")),
            str(branding.get("instagram_handle", "@yourinstagram")))),
        "channel_logo": ("assets/channel_logo.png", lambda p: make_panda_logo(
            p, str(branding.get("channel_name", "YOUR CHANNEL")))),
    }
    for layer_name, (default_rel, generator) in defaults.items():
        layer = config.get("layers", {}).get(layer_name)
        if not layer or not layer.get("asset"):
            continue
        path = Path(layer["asset"])
        if not path.is_absolute():
            path = config_path.parent / path
        path = path.resolve()
        if not path.is_file():
            # Artwork missing (e.g. the template was shared to a machine without the
            # original files): fall back to the generated starter image so the layer
            # still renders, and keep the config pointing at the portable copy.
            fallback = (config_path.parent / default_rel).resolve()
            fallback.parent.mkdir(parents=True, exist_ok=True)
            generator(fallback)
            layer["asset"] = default_rel
            output[layer_name] = fallback
            continue
        output[layer_name] = path
        if path == (config_path.parent / default_rel).resolve():
            path.parent.mkdir(parents=True, exist_ok=True)
            generator(path)
    return output
