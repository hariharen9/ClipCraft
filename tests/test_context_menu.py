from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from clipcraft.context_menu import (
    MENU_KEY_NAME,
    MENU_TITLE,
    VIDEO_ASSOCIATIONS,
    get_launch_command_and_icon,
    is_context_menu_registered,
    register_context_menu,
    unregister_context_menu,
)


def test_get_launch_command_and_icon_explicit():
    fake_exe = Path("C:/Custom/Path/ClipCraft.exe")
    cmd, icon = get_launch_command_and_icon(fake_exe)
    assert f'"{fake_exe.resolve()}" "%1"' == cmd
    assert str(fake_exe.resolve()) == icon


def test_get_launch_command_and_icon_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/App/ClipCraft.exe")
    cmd, icon = get_launch_command_and_icon()
    assert '"C:\\App\\ClipCraft.exe" "%1"' == cmd
    assert "C:\\App\\ClipCraft.exe" == icon


def test_get_launch_command_and_icon_script_fallback(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    orig_is_file = Path.is_file

    def fake_is_file(self):
        s = str(self)
        if "Programs\\ClipCraft" in s or "dist\\ClipCraft" in s:
            return False
        return orig_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    cmd, icon = get_launch_command_and_icon()
    assert "clipcraft.py" in cmd
    assert '"%1"' in cmd


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry only")
def test_register_and_unregister_context_menu():
    import winreg

    # Test registration
    ok = register_context_menu()
    assert ok is True
    assert is_context_menu_registered() is True

    # Verify keys actually exist in HKCU
    for assoc in VIDEO_ASSOCIATIONS:
        shell_key = rf"Software\Classes\{assoc}\shell\{MENU_KEY_NAME}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, shell_key) as key:
            val, _ = winreg.QueryValueEx(key, "")
            assert val == MENU_TITLE

        cmd_key = rf"{shell_key}\command"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cmd_key) as key:
            cmd_val, _ = winreg.QueryValueEx(key, "")
            assert "%1" in cmd_val

    # Test unregistration
    ok_unreg = unregister_context_menu()
    assert ok_unreg is True
    assert is_context_menu_registered() is False

    # Restore registration for the user
    register_context_menu()
    assert is_context_menu_registered() is True


def test_non_windows_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert register_context_menu() is False
    assert unregister_context_menu() is False
    assert is_context_menu_registered() is False


def test_cli_context_menu_flags():
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("clipcraft_script", root / "clipcraft.py")
    clipcraft_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clipcraft_script)

    parser = clipcraft_script.build_parser()
    args_reg = parser.parse_args(["--register-context-menu"])
    assert args_reg.register_context_menu is True

    args_unreg = parser.parse_args(["--unregister-context-menu"])
    assert args_unreg.unregister_context_menu is True
