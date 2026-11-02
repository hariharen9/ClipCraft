"""FasTrack quick-edit launcher.

Drop one or more video files onto this icon in Explorer and the FasTrack editor
opens with the first clip already loaded — no console window, no Browse step.
Double-clicking it opens the editor empty (it remembers your last source folder).

Requires install.bat to have been run once (creates the .venv folder).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


def main() -> int:
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "FasTrack",
                "The .venv folder is missing.\n\nRun install.bat once to set up FasTrack,\nthen use quick_edit.pyw again.",
            )
        except Exception:
            pass
        return 2
    clips = [arg for arg in sys.argv[1:] if Path(arg).suffix.lower() in VIDEO_SUFFIXES]
    command = [str(pythonw), str(ROOT / "fasttrack.py")]
    if clips:
        command.append(clips[0])
    command.append("--gui")
    subprocess.Popen(command, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
