from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Any

from .config import contain_fit, image_content_info, resolve_asset

ProgressCallback = Callable[[float, str], None]


def find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError(
            "FFmpeg was not found. Install a full FFmpeg build and add its bin folder to PATH."
        )
    return found


def probe_video(path: str | Path, ffprobe: str | None = None) -> dict[str, Any]:
    video_path = Path(path).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")
    ffprobe = ffprobe or shutil.which("ffprobe") or "ffprobe"
    cmd = [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe could not read this video")
    data = json.loads(result.stdout)
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video_stream is None:
        raise ValueError("The selected file does not contain a video stream")
    duration = float(data.get("format", {}).get("duration") or video_stream.get("duration") or 0)
    fps_text = video_stream.get("avg_frame_rate", "0/1")
    try:
        num, den = fps_text.split("/")
        fps = float(num) / max(float(den), 1.0)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "duration": duration,
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
        "codec": video_stream.get("codec_name", "unknown"),
    }


def _even(value: float, minimum: int = 2) -> int:
    number = max(minimum, int(round(value)))
    return number if number % 2 == 0 else number - 1


def _rect_pixels(rect: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = [float(v) for v in rect]
    px = int(round(x * width))
    py = int(round(y * height))
    pw = _even(w * width)
    ph = _even(h * height)
    px = max(0, min(width - 2, px))
    py = max(0, min(height - 2, py))
    pw = min(pw, width - px)
    ph = min(ph, height - py)
    return px, py, max(2, pw), max(2, ph)


def _crop_expr(crop: list[float]) -> str:
    x, y, w, h = [float(v) for v in crop]
    x = max(0.0, min(0.995, x))
    y = max(0.0, min(0.995, y))
    w = max(0.005, min(w, 1.0 - x))
    h = max(0.005, min(h, 1.0 - y))
    # FFmpeg evaluates these expressions against the actual input dimensions.
    return (
        f"crop=w='iw*{w:.6f}':h='ih*{h:.6f}':"
        f"x='iw*{x:.6f}':y='ih*{y:.6f}'"
    )


def build_filter_complex(
    config: dict[str, Any],
    config_path: Path,
    video_info: dict[str, Any],
) -> tuple[str, list[Path]]:
    canvas = config.get("canvas", {})
    out_w, out_h = int(canvas.get("width", 1080)), int(canvas.get("height", 1920))
    fps = int(canvas.get("fps", 60))
    layers = config.get("layers", {})
    background = config.get("background", {})
    video_names = [
        name for name, layer in sorted(layers.items(), key=lambda pair: pair[1].get("z", 0))
        if layer.get("kind") == "video" and layer.get("visible", True)
    ]
    if "main" not in video_names:
        raise ValueError("Valorant template needs a visible 'main' video layer")
    split_labels = [f"vsrc{i}" for i in range(len(video_names) + 1)]
    split_outputs = "".join(f"[{label}]" for label in split_labels)
    parts = [f"[0:v]fps={fps},split={len(split_labels)}{split_outputs}"]

    # Blurred full-frame background. It is intentionally downscaled before blur to keep 60 fps practical.
    bg_blur = max(1, int(background.get("blur", 22)))
    bg_brightness = float(background.get("brightness", -0.08))
    bg_saturation = float(background.get("saturation", 0.82))
    parts.append(
        f"[vsrc0]scale={max(2, out_w // 2)}:{max(2, out_h // 2)}:force_original_aspect_ratio=increase,"
        f"crop={max(2, out_w // 2)}:{max(2, out_h // 2)},boxblur={bg_blur}:2,"
        f"eq=brightness={bg_brightness:.4f}:saturation={bg_saturation:.4f},"
        f"scale={out_w}:{out_h}[base0]"
    )
    current = "base0"
    source_index = 1
    for index, name in enumerate(video_names, start=1):
        layer = layers[name]
        if name == "background":
            continue
        x, y, w, h = _rect_pixels(layer.get("rect", [0, 0, 1, 1]), out_w, out_h)
        crop = layer.get("crop", [0, 0, 1, 1])
        crop_filter = _crop_expr(crop)
        fit = layer.get("fit", "cover")
        if fit == "contain":
            filter_body = (
                f"{crop_filter},scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        else:
            filter_body = f"{crop_filter},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        label = f"lay_{name}"
        parts.append(f"[vsrc{index}]{filter_body}[{label}]")
        next_label = f"comp{index}"
        parts.append(f"[{current}][{label}]overlay={x}:{y}:eof_action=pass:shortest=1[{next_label}]")
        current = next_label

    image_inputs: list[Path] = []
    input_index = 1
    image_names = [
        name for name, layer in sorted(layers.items(), key=lambda pair: pair[1].get("z", 0))
        if layer.get("kind") == "image" and layer.get("visible", True)
    ]
    # Image inputs are added after the source clip, in exactly this order by build_ffmpeg_command.
    for image_number, name in enumerate(image_names):
        layer = layers[name]
        asset = resolve_asset(config_path, layer.get("asset", ""))
        if not asset.is_file():
            raise FileNotFoundError(f"Asset for layer '{name}' not found: {asset}")
        image_inputs.append(asset)
        x, y, w, h = _rect_pixels(layer.get("rect", [0, 0, 0.1, 0.1]), out_w, out_h)
        opacity = max(0.0, min(1.0, float(layer.get("opacity", 1.0))))
        # Transparent padding is trimmed so the visible content defines shape and aspect.
        native_w, native_h, bbox = image_content_info(asset)
        source_w, source_h = native_w, native_h
        trim = ""
        if bbox is not None and tuple(bbox) != (0, 0, native_w, native_h):
            source_w, source_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            trim = f"crop={source_w}:{source_h}:{bbox[0]}:{bbox[1]},"
        if layer.get("fit", "contain") == "fill":
            draw_w, draw_h, draw_x, draw_y = w, h, x, y
        else:
            # Keep the asset's original aspect ratio, centered inside the layer rectangle.
            draw_w, draw_h = contain_fit(source_w, source_h, w, h)
            draw_x = x + (w - draw_w) // 2
            draw_y = y + (h - draw_h) // 2
        image_label = f"img_{name}"
        parts.append(
            f"[{input_index}:v]format=rgba,{trim}scale={draw_w}:{draw_h},"
            f"colorchannelmixer=aa={opacity:.4f}[{image_label}]"
        )
        next_label = f"comp_img{image_number}"
        parts.append(f"[{current}][{image_label}]overlay={draw_x}:{draw_y}:eof_action=pass:shortest=1[{next_label}]")
        current = next_label
        input_index += 1

    parts.append(f"[{current}]format=yuv420p[outv]")
    return ";".join(parts), image_inputs


def build_ffmpeg_command(
    video_path: str | Path,
    output_path: str | Path,
    start: float,
    end: float,
    config: dict[str, Any],
    config_path: Path,
    encoder: str = "auto",
) -> tuple[list[str], float]:
    video_path = Path(video_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Input video not found: {video_path}")
    if start < 0 or end <= start:
        raise ValueError("Clip OUT must be greater than IN, and IN cannot be negative")
    info = probe_video(video_path)
    if info["duration"] and end > info["duration"] + 0.05:
        raise ValueError(f"Clip OUT ({end:.2f}s) exceeds video duration ({info['duration']:.2f}s)")
    duration = end - start
    graph, image_inputs = build_filter_complex(config, config_path, info)
    fps = int(config.get("canvas", {}).get("fps", 60))
    command = [find_ffmpeg(), "-hide_banner", "-y", "-loglevel", "error", "-ss", f"{start:.6f}", "-i", str(video_path)]
    for image_path in image_inputs:
        command += ["-loop", "1", "-framerate", str(fps), "-i", str(image_path)]
    command += [
        "-filter_complex_threads", "4",
        "-filter_complex", graph,
        "-map", "[outv]", "-map", "0:a?",
        "-t", f"{duration:.6f}",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-af", "aresample=async=1:first_pts=0",
        "-movflags", "+faststart",
    ]
    canvas = config.get("canvas", {})
    quality = int(canvas.get("quality", 19))
    if encoder == "auto":
        encoder = str(canvas.get("encoder", "auto"))
    if encoder in ("auto", "nvenc"):
        preset = str(canvas.get("nvenc_preset", "p5"))
        command += [
            "-c:v", "h264_nvenc", "-preset", preset,
            "-tune", "hq", "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
            "-profile:v", "high", "-spatial-aq", "1", "-temporal-aq", "1",
        ]
    elif encoder in ("cpu", "libx264"):
        preset = str(canvas.get("x264_preset", "medium"))
        command += ["-c:v", "libx264", "-preset", preset, "-crf", str(quality), "-profile:v", "high"]
    else:
        raise ValueError(f"Unknown encoder choice: {encoder}")
    command += ["-progress", "pipe:1", "-nostats", str(output_path)]
    return command, duration


def run_render(
    video_path: str | Path,
    output_path: str | Path,
    start: float,
    end: float,
    config: dict[str, Any],
    config_path: Path,
    encoder: str = "auto",
    progress: ProgressCallback | None = None,
) -> Path:
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command, duration = build_ffmpeg_command(
        video_path, output_path, start, end, config, config_path, encoder
    )
    active_encoder = encoder if encoder != "auto" else str(config.get("canvas", {}).get("encoder", "auto"))
    if active_encoder not in ("auto", "nvenc") and "h264_nvenc" in command:
        active_encoder = "auto"

    def launch(cmd: list[str]) -> tuple[int, str]:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1
        )
        assert process.stdout is not None
        latest_time = 0.0
        for line in process.stdout:
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    latest_time = int(line.split("=", 1)[1]) / 1_000_000.0
                    percent = max(0.0, min(100.0, latest_time / max(duration, 0.001) * 100.0))
                    if progress:
                        progress(percent, f"Rendering… {percent:.0f}%")
                except ValueError:
                    pass
            elif line == "progress=end" and progress:
                progress(100.0, "Finalizing video…")
        stderr = process.stderr.read() if process.stderr else ""
        return process.wait(), stderr

    code, error = launch(command)
    if code != 0 and active_encoder == "auto" and "h264_nvenc" in command:
        if progress:
            progress(0.0, "NVENC unavailable; retrying with CPU encoding…")
        cpu_command, _ = build_ffmpeg_command(
            video_path, output_path, start, end, config, config_path, "cpu"
        )
        code, error = launch(cpu_command)
    if code != 0:
        raise RuntimeError(error.strip() or f"FFmpeg exited with code {code}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg reported success but no output video was created")
    if progress:
        progress(100.0, "Render complete")
    return output_path
