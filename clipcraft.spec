# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

ROOT = Path.cwd()

datas = [
    (str(ROOT / "templates"), "templates"),
]

# Collect qtawesome vector font resources (crucial for icons)
try:
    datas += collect_data_files("qtawesome")
except Exception:
    pass

# Collect faster_whisper & ctranslate2 assets
try:
    datas += collect_data_files("faster_whisper")
except Exception:
    pass

try:
    datas += collect_data_files("ctranslate2")
except Exception:
    pass

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtSvg",
    "cv2",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageFilter",
    "numpy",
    "qtawesome",
    "ctranslate2",
    "faster_whisper",
    "tokenizers",
    "clipcraft",
    "clipcraft.assets",
    "clipcraft.captions",
    "clipcraft.config",
    "clipcraft.preview",
    "clipcraft.renderer",
    "clipcraft.gui",
    "clipcraft.gui.audio_dialog",
    "clipcraft.gui.caption_dialog",
    "clipcraft.gui.canvas_items",
    "clipcraft.gui.constants",
    "clipcraft.gui.crop_dialog",
    "clipcraft.gui.inspector",
    "clipcraft.gui.layer_stack",
    "clipcraft.gui.main_window",
    "clipcraft.gui.transport_bar",
    "clipcraft.gui.worker",
    "clipcraft.gui.batch_window",
]

try:
    hiddenimports += collect_submodules("ctranslate2")
    hiddenimports += collect_submodules("faster_whisper")
except Exception:
    pass

icon_file = ROOT / "clipcraft.ico"
icon_path = str(icon_file) if icon_file.is_file() else None

a = Analysis(
    ["clipcraft.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "notebook", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClipCraft",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ClipCraft",
)

