"""Windows Explorer context menu integration for ClipCraft.

Registers 'Open in ClipCraft' under SystemFileAssociations/video and specific
video formats (.mp4, .mkv, .mov, .avi, .webm) in HKEY_CURRENT_USER\\Software\\Classes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .config import APP_DIR

VIDEO_ASSOCIATIONS: tuple[str, ...] = (
    r"SystemFileAssociations\video",
    r"SystemFileAssociations\.mp4",
    r"SystemFileAssociations\.mkv",
    r"SystemFileAssociations\.mov",
    r"SystemFileAssociations\.avi",
    r"SystemFileAssociations\.webm",
)
MENU_TITLE = "Open in ClipCraft"
MENU_KEY_NAME = "ClipCraft"


def get_launch_command_and_icon(
    exe_path: str | Path | None = None,
) -> tuple[str, str | None]:
    """Resolve the command-line invocation and icon path for the context menu."""
    if exe_path:
        target = Path(exe_path).expanduser().resolve()
        return f'"{target}" "%1"', str(target)

    # 1. Running as frozen PyInstaller binary
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}" "%1"', str(exe)

    # 2. Check for installed ClipCraft.exe (User local or Program Files)
    local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ClipCraft" / "ClipCraft.exe"
    if local_app.is_file():
        return f'"{local_app.resolve()}" "%1"', str(local_app.resolve())

    prog_files = Path(os.environ.get("ProgramFiles", "")) / "ClipCraft" / "ClipCraft.exe"
    if prog_files.is_file():
        return f'"{prog_files.resolve()}" "%1"', str(prog_files.resolve())

    # 3. Check for locally compiled portable build
    dist_exe = APP_DIR / "dist" / "ClipCraft" / "ClipCraft.exe"
    if dist_exe.is_file():
        return f'"{dist_exe.resolve()}" "%1"', str(dist_exe.resolve())

    # 4. Fallback: Python script invocation
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    py_bin = pythonw if pythonw.is_file() else Path(sys.executable)
    script = (APP_DIR / "clipcraft.py").resolve()
    icon = (APP_DIR / "clipcraft.ico").resolve()
    icon_str = str(icon) if icon.is_file() else None
    return f'"{py_bin.resolve()}" "{script}" "%1"', icon_str


def register_context_menu(exe_path: str | Path | None = None) -> bool:
    """Register 'Open in ClipCraft' context menu in HKCU for video files."""
    if sys.platform != "win32":
        return False
    import winreg

    cmd, icon = get_launch_command_and_icon(exe_path)

    try:
        for assoc in VIDEO_ASSOCIATIONS:
            shell_key = rf"Software\Classes\{assoc}\shell\{MENU_KEY_NAME}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, shell_key) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, MENU_TITLE)
                if icon:
                    winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, str(icon))

            cmd_key = rf"{shell_key}\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd)
        return True
    except Exception as exc:
        print(f"[ClipCraft] Failed to register context menu: {exc}", file=sys.stderr)
        return False


def unregister_context_menu() -> bool:
    """Remove 'Open in ClipCraft' context menu from HKCU."""
    if sys.platform != "win32":
        return False
    import winreg

    success = True
    for assoc in VIDEO_ASSOCIATIONS:
        shell_key = rf"Software\Classes\{assoc}\shell\{MENU_KEY_NAME}"
        cmd_key = rf"{shell_key}\command"

        # Delete child command key first
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, cmd_key)
        except FileNotFoundError:
            pass
        except Exception:
            success = False

        # Delete parent verb key
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, shell_key)
        except FileNotFoundError:
            pass
        except Exception:
            success = False
    return success


def is_context_menu_registered() -> bool:
    """Check if 'Open in ClipCraft' context menu is registered in HKCU."""
    if sys.platform != "win32":
        return False
    import winreg

    test_key = rf"Software\Classes\{VIDEO_ASSOCIATIONS[0]}\shell\{MENU_KEY_NAME}\command"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, test_key) as key:
            val, _ = winreg.QueryValueEx(key, "")
            return bool(val)
    except (FileNotFoundError, OSError):
        return False
