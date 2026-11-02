"""Build FasTrack.exe with PyInstaller.

Creates dist\\FasTrack\\ — a self-contained folder with FasTrack.exe plus the
bundled game templates. Zip that folder to share FasTrack; recipients only need
FFmpeg (and ffprobe) on PATH and an NVIDIA driver for NVENC (CPU fallback works).

Usage:  .venv\\Scripts\\python.exe build_exe.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller…")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller>=6.0"], check=True)

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",       # no console window; GUI only
        "--onedir",         # fast startup (onefile adds a long PySide6 extraction)
        "--name", "FasTrack",
        "--icon", str(ROOT / "assets" / "fastrack.ico"),
        "--add-data", f"{ROOT / 'templates'};templates",
        str(ROOT / "fasttrack.py"),
    ]
    print("Running PyInstaller…")
    subprocess.run(command, cwd=str(ROOT), check=True)
    exe = ROOT / "dist" / "FasTrack" / "FasTrack.exe"
    print(f"\nBuilt: {exe}")
    print("Templates are copied next to the exe on first launch and stay user-editable there.")
    print("Tip: swap --onedir for --onefile in this script for a single-file build (slower startup).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
