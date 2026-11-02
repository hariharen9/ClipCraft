from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fasttrack.assets import ensure_assets
from fasttrack.config import load_config
from fasttrack.renderer import run_render, probe_video


def parse_time(value: str) -> float:
    """Parse seconds, MM:SS, or HH:MM:SS.mmm."""
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("Time cannot be empty")
    try:
        if ":" not in value:
            seconds = float(value)
        else:
            parts = value.split(":")
            if len(parts) == 2:
                minutes, seconds_part = parts
                seconds = int(minutes) * 60 + float(seconds_part)
            elif len(parts) == 3:
                hours, minutes, seconds_part = parts
                seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds_part)
            else:
                raise ValueError
        if seconds < 0:
            raise ValueError
        return seconds
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid time '{value}'. Use seconds, MM:SS, or HH:MM:SS.mmm."
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fasttrack",
        description="FasTrack — turn gameplay recordings into vertical gaming Shorts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("video", nargs="?", help="Input recording (MP4, MKV, MOV, AVI, WEBM)")
    parser.add_argument("-g", "--game", default="valorant", help="Game template (currently: valorant)")
    parser.add_argument("--in", dest="in_time", type=parse_time, help="Clip IN point (seconds, MM:SS, or HH:MM:SS)")
    parser.add_argument("--out", dest="out_time", type=parse_time, help="Clip OUT point (seconds, MM:SS, or HH:MM:SS)")
    parser.add_argument("-o", "--output", help="Output MP4 path")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--encoder", choices=("auto", "nvenc", "cpu"), default="auto", help="GPU/CPU encoder")
    parser.add_argument("--gui", "-gui", action="store_true", help="Open the visual editor")
    parser.add_argument("--render", action="store_true", help="Render headlessly (requires --in and --out)")
    parser.add_argument("--print-command", action="store_true", help="Print the generated FFmpeg command and exit")
    return parser


def default_output(video_path: Path, game: str) -> Path:
    return video_path.parent / "exports" / f"{video_path.stem}_{game}_short.mp4"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    game = args.game.lower()
    if game != "valorant":
        parser.error(f"Template '{game}' is not available yet. Start with -g valorant.")

    try:
        config, config_path = load_config(args.config)
        ensure_assets(config, config_path)
    except Exception as exc:
        print(f"[FasTrack] Config error: {exc}", file=sys.stderr)
        return 2

    if args.gui or not args.render and (args.in_time is None or args.out_time is None):
        try:
            from fasttrack.gui import launch_gui
            return int(launch_gui(args.video, game, args.config) or 0)
        except ImportError as exc:
            print(
                "[FasTrack] GUI dependencies are missing. Run: py -m pip install -r requirements.txt\n"
                f"Details: {exc}", file=sys.stderr
            )
            return 2
        except Exception as exc:
            print(f"[FasTrack] Could not start GUI: {exc}", file=sys.stderr)
            return 2

    if not args.video:
        parser.error("Provide an input video path, or run with --gui to browse for one.")
    if args.in_time is None or args.out_time is None:
        parser.error("Headless rendering requires both --in and --out.")
    video_path = Path(args.video).expanduser().resolve()
    try:
        info = probe_video(video_path)
        if args.out_time > info["duration"] + 0.05:
            parser.error(f"--out exceeds the recording duration ({info['duration']:.3f} seconds).")
        output_path = Path(args.output).expanduser().resolve() if args.output else default_output(video_path, game)
        if args.print_command:
            from fasttrack.renderer import build_ffmpeg_command
            command, duration = build_ffmpeg_command(
                video_path, output_path, args.in_time, args.out_time,
                config, config_path, args.encoder
            )
            print(" ".join(f'"{part}"' if " " in part else part for part in command))
            print(f"\nClip duration: {duration:.3f}s | Source: {info['width']}x{info['height']} @ {info['fps']:.2f} fps")
            return 0

        print(f"FasTrack · Valorant · {info['width']}x{info['height']} @ {info['fps']:.2f} fps")
        print(f"IN {args.in_time:.3f}s → OUT {args.out_time:.3f}s ({args.out_time - args.in_time:.3f}s)")
        print(f"Output: {output_path}")

        last_percent = -1
        def on_progress(value: float, message: str):
            nonlocal last_percent
            percent = int(value)
            if percent != last_percent or value == 0:
                print(f"\r{message:<55}", end="", flush=True)
                last_percent = percent

        rendered = run_render(
            video_path, output_path, args.in_time, args.out_time,
            config, config_path, args.encoder, on_progress
        )
        print(f"\n\nDone: {rendered}")
        return 0
    except Exception as exc:
        print(f"\n[FasTrack] Render failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
