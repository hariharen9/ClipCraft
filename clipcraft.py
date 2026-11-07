from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clipcraft.assets import ensure_assets
from clipcraft.config import load_config
from clipcraft.renderer import run_render, probe_video


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
        prog="clipcraft",
        description="ClipCraft — turn gameplay recordings into vertical gaming Shorts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("video", nargs="?", help="Input recording (MP4, MKV, MOV, AVI, WEBM)")
    parser.add_argument("-g", "--game", default=None, help="Game template from templates/ (default: valorant)")
    parser.add_argument("--in", dest="in_time", type=parse_time, help="Clip IN point (seconds, MM:SS, or HH:MM:SS)")
    parser.add_argument("--out", dest="out_time", type=parse_time, help="Clip OUT point (seconds, MM:SS, or HH:MM:SS)")
    parser.add_argument("-o", "--output", help="Output MP4 path")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--encoder", choices=("auto", "nvenc", "cpu"), default="auto", help="GPU/CPU encoder")
    parser.add_argument("--gui", "-gui", action="store_true", help="Open the visual editor")
    parser.add_argument("--batch", action="store_true", help="Open the batch render UI")
    parser.add_argument("--render", action="store_true", help="Render headlessly (requires --in and --out)")
    parser.add_argument("--bgm", help="Path to background music audio file (.mp3, .wav, .m4a)")
    parser.add_argument("--bgm-volume", type=float, default=None, help="BGM volume multiplier (0.0 to 2.0, default: 0.35)")
    parser.add_argument("--gameplay-volume", type=float, default=None, help="Gameplay volume multiplier (0.0 to 2.0, default: 1.0)")
    parser.add_argument("--no-ducking", action="store_true", help="Disable auto-ducking on background music")
    parser.add_argument("--audio-fade", type=float, default=None, help="Duration in seconds for audio fade in and out (default: 0.5)")
    parser.add_argument("--print-command", action="store_true", help="Print the generated FFmpeg command and exit")
    return parser


def default_output(video_path: Path, game: str) -> Path:
    return video_path.parent / "exports" / f"{video_path.stem}_{game}_short.mp4"


def _log_crash(message: str, exc: BaseException | None = None) -> None:
    """Write error/crash details to stderr and append to clipcraft.log."""
    import datetime
    import traceback
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb = traceback.format_exc() if exc is not None else ""
    formatted = f"[{timestamp}] {message}\n"
    if tb and tb.strip() != "NoneType: None":
        formatted += f"{tb}\n"
    print(formatted, file=sys.stderr, flush=True)
    try:
        log_file = Path(__file__).resolve().parent / "clipcraft.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(formatted)
    except Exception:
        pass


def _setup_crash_logging() -> None:
    """Install an excepthook to capture any unhandled crash to clipcraft.log."""
    def _hook(exc_type, exc_value, exc_tb):
        import datetime
        import traceback
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        formatted = f"[{timestamp}] UNHANDLED EXCEPTION:\n{tb}\n"
        print(formatted, file=sys.stderr, flush=True)
        try:
            log_file = Path(__file__).resolve().parent / "clipcraft.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(formatted)
        except Exception:
            pass
    sys.excepthook = _hook


def main(argv: list[str] | None = None) -> int:
    _setup_crash_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    game = (args.game or "").lower() or None

    if args.batch:
        try:
            from clipcraft.gui import launch_batch_gui
            return int(launch_batch_gui(game, args.config) or 0)
        except ImportError as exc:
            _log_crash(
                "[ClipCraft] GUI dependencies are missing. Run install.bat to install them.\n"
                f"Details: {exc}", exc
            )
            return 2
        except Exception as exc:
            _log_crash(f"[ClipCraft] Could not start batch UI: {exc}", exc)
            return 2

    if args.gui or not args.render and (args.in_time is None or args.out_time is None):
        # The GUI resolves the template itself: --config, -g, or the last used one.
        try:
            from clipcraft.gui import launch_gui
            return int(launch_gui(args.video, game, args.config) or 0)
        except ImportError as exc:
            _log_crash(
                "[ClipCraft] GUI dependencies are missing. Run install.bat to install them.\n"
                f"Details: {exc}", exc
            )
            return 2
        except Exception as exc:
            _log_crash(f"[ClipCraft] Could not start GUI: {exc}", exc)
            return 2

    if not args.video:
        parser.error("Provide an input video path, or run with --gui to browse for one.")
    if args.in_time is None or args.out_time is None:
        parser.error("Headless rendering requires both --in and --out.")
    video_path = Path(args.video).expanduser().resolve()
    try:
        info = probe_video(video_path)
        if args.config:
            config, config_path = load_config(args.config)
        else:
            from clipcraft.config import migrate_legacy_config, template_path, available_templates
            migrate_legacy_config()
            game_id = game or "valorant"
            template = template_path(game_id)
            if not template.is_file():
                names = ", ".join(name for _, name in available_templates()) or "none installed"
                parser.error(f"Template '{game_id}' not found in templates/. Available: {names}")
            config, config_path = load_config(template)
        ensure_assets(config, config_path)
        game_id = game or (args.config and Path(args.config).stem.lower()) or "valorant"
        if args.out_time > info["duration"] + 0.05:
            parser.error(f"--out exceeds the recording duration ({info['duration']:.3f} seconds).")

        audio_config = {}
        if args.bgm:
            audio_config["bgm_path"] = args.bgm
        if args.bgm_volume is not None:
            audio_config["bgm_volume"] = args.bgm_volume
        if args.gameplay_volume is not None:
            audio_config["gameplay_volume"] = args.gameplay_volume
        if args.no_ducking:
            audio_config["auto_ducking"] = False
        if args.audio_fade is not None:
            audio_config["fade_in"] = args.audio_fade
            audio_config["fade_out"] = args.audio_fade
        if audio_config:
            config.setdefault("audio", {}).update(audio_config)

        output_path = Path(args.output).expanduser().resolve() if args.output else default_output(video_path, game_id)
        if args.print_command:
            from clipcraft.renderer import build_ffmpeg_command
            command, duration = build_ffmpeg_command(
                video_path, output_path, args.in_time, args.out_time,
                config, config_path, args.encoder, audio_config=config.get("audio")
            )
            print(" ".join(f'"{part}"' if " " in part else part for part in command))
            print(f"\nClip duration: {duration:.3f}s | Source: {info['width']}x{info['height']} @ {info['fps']:.2f} fps")
            return 0

        print(f"ClipCraft · {game_id.title()} · {info['width']}x{info['height']} @ {info['fps']:.2f} fps")
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
            config, config_path, args.encoder, on_progress, audio_config=config.get("audio")
        )
        print(f"\n\nDone: {rendered}")
        return 0
    except Exception as exc:
        _log_crash(f"[ClipCraft] Render failed: {exc}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
