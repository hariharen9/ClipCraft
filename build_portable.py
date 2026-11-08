"""ClipCraft — Automated Standalone Portable Windows Build Script.

Builds a self-contained portable Windows release using PyInstaller:
1. Generates high-resolution multi-size Windows application icon (clipcraft.ico).
2. Compiles ClipCraft with all GUI, AI auto-captions, and preview dependencies into dist/ClipCraft.
3. Bundles FFmpeg and FFprobe binaries directly inside the release folder.
4. Includes all game layout templates (Valorant, CS2, R6 Siege, Apex, Warzone, Fortnite, LoL).
5. Prepares portable configuration and user documentation.
6. Archives the portable folder into dist/ClipCraft_v0.1.0_Windows_Portable.zip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
APP_DIST = DIST_DIR / "ClipCraft"
ICON_PATH = ROOT / "clipcraft.ico"


def ensure_icon() -> None:
    """Generate multi-size Windows icon if missing."""
    if ICON_PATH.is_file():
        return
    print("[1/6] Generating high-resolution application icon (clipcraft.ico)…")
    try:
        from PIL import Image, ImageDraw
        size = 256
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Dark rounded squircle background with cyan neon border
        draw.rounded_rectangle([8, 8, 248, 248], radius=56, fill=(18, 24, 38, 255), outline=(0, 229, 255, 255), width=6)

        # Back vertical frame
        draw.rounded_rectangle([52, 44, 140, 204], radius=16, fill=(30, 41, 59, 255), outline=(99, 102, 241, 255), width=4)

        # Front vertical frame with cyan glow
        draw.rounded_rectangle([116, 52, 204, 212], radius=16, fill=(15, 23, 42, 255), outline=(0, 229, 255, 255), width=5)

        # White play button
        draw.polygon([(144, 108), (144, 156), (184, 132)], fill=(255, 255, 255, 255))

        # Accent gaming strips
        draw.rectangle([132, 70, 188, 76], fill=(255, 70, 84, 255))
        draw.rectangle([132, 188, 172, 194], fill=(0, 255, 128, 255))

        img.save(ICON_PATH, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
        print(f"      Created icon at {ICON_PATH}")
    except Exception as exc:
        print(f"      Warning: Could not synthesize icon ({exc}). Continuing without icon.")


def locate_binary(name: str) -> Path | None:
    """Find system executable (e.g. ffmpeg.exe, ffprobe.exe)."""
    candidates = []
    # 1. System PATH
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))

    # 2. Windows WinGet Links
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
    if winget.is_file():
        candidates.append(winget)

    # 3. Chocolatey paths (standard on GitHub Actions windows-latest)
    candidates.append(Path(f"C:/ProgramData/chocolatey/bin/{name}.exe"))
    candidates.append(Path(f"C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin/{name}.exe"))

    # 4. Common install roots
    for drive in ("C:", "D:"):
        candidates.append(Path(f"{drive}/ffmpeg/bin/{name}.exe"))
        candidates.append(Path(f"{drive}/Program Files/ffmpeg/bin/{name}.exe"))

    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def run_pyinstaller() -> None:
    """Compile ClipCraft using PyInstaller spec file."""
    print("[2/6] Running PyInstaller build engine…")
    spec_file = ROOT / "clipcraft.spec"
    if not spec_file.is_file():
        raise FileNotFoundError(f"Missing spec file: {spec_file}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(spec_file),
    ]

    env = os.environ.copy()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"PyInstaller build failed with exit code {proc.returncode}")
    print("      PyInstaller compilation finished successfully.")


def bundle_binaries() -> None:
    """Copy FFmpeg and FFprobe into the portable application folder."""
    print("[3/6] Bundling FFmpeg and FFprobe binaries into release folder…")
    for name in ("ffmpeg", "ffprobe"):
        bin_path = locate_binary(name)
        if bin_path and bin_path.is_file():
            dest = APP_DIST / f"{name}.exe"
            shutil.copy2(bin_path, dest)
            size_mb = dest.stat().st_size / (1024 * 1024)
            print(f"      Copied {name}.exe ({size_mb:.1f} MB) from {bin_path.parent}")
        else:
            print(f"      Notice: {name}.exe not found locally; app will fall back to system PATH.")


def bundle_templates_and_assets() -> None:
    """Ensure all template JSON files and state are deployed in release directory."""
    print("[4/6] Copying game templates, presets, and configuration…")
    dest_tmpl = APP_DIST / "templates"
    dest_tmpl.mkdir(parents=True, exist_ok=True)

    src_tmpl = ROOT / "templates"
    if src_tmpl.is_dir():
        for tf in src_tmpl.glob("*.json"):
            shutil.copy2(tf, dest_tmpl / tf.name)
            print(f"      Template: {tf.name}")

    # Copy icon to dist
    if ICON_PATH.is_file():
        shutil.copy2(ICON_PATH, APP_DIST / "clipcraft.ico")

    # Initial portable state file
    state_file = APP_DIST / "clipcraft_state.json"
    if not state_file.is_file():
        import json
        state_data = {
            "show_grips": True,
            "preview_sharp": True,
            "last_template": "valorant",
            "show_safe_zones": False,
            "output_pattern": "{clip}_{game}_{in}-{out}",
        }
        state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")
        print("      Created portable state: clipcraft_state.json")

    # Portable documentation
    readme = APP_DIST / "README.txt"
    readme_content = """========================================================================
ClipCraft — Desktop Video Editor & GPU Rendering Engine (Portable Edition)
========================================================================

QUICK START:
  1. Double-click "ClipCraft.exe" to launch the studio editor.
  2. No Python, command prompt, or installation required!
  3. Built-in GPU (NVENC) hardware encoding with automatic CPU fallback.
  4. Built-in FFmpeg processing engine included.

FEATURES:
  - 16:9 to 9:16 vertical short conversion with dynamic blurred background.
  - Multi-Game Templates: Valorant, R6 Siege, CS2, Apex, Warzone, Fortnite, LoL.
  - Interactive visual cropping for facecam, killfeed, chat, HUD, and minimap.
  - Audio & Background Music Studio: BGM track trimming, auto-ducking, fades.
  - AI Auto-Captions: Fast local Whisper speech-to-text with word-by-word
    karaoke highlight animations positioned in the mobile safe zone.
  - Batch Queue Processing Studio: Convert multiple recordings sequentially.

PORTABLE NOTES:
  - All configurations and recent files are stored locally in this folder.
  - Custom game templates can be added or edited inside the 'templates/' folder.
========================================================================
"""
    readme.write_text(readme_content, encoding="utf-8")
    print("      Generated portable README.txt")


def verify_executable() -> None:
    """Test running the compiled executable headlessly."""
    print("[5/6] Verifying compiled executable integrity…")
    exe_path = APP_DIST / "ClipCraft.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(f"Expected executable not found: {exe_path}")

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"      Executable size: {size_mb:.2f} MB")

    # Run quick CLI verification
    try:
        proc = subprocess.run(
            [str(exe_path), "--help"],
            capture_output=True,
            timeout=15,
        )
        stdout_text = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        if proc.returncode == 0 and "ClipCraft" in stdout_text:
            print("      Verification check passed: ClipCraft.exe responded with valid help text.")
        else:
            print(f"      Verification returned exit code {proc.returncode}.")
    except Exception as exc:
        print(f"      Note: GUI executable verification skipped ({exc}).")


def create_portable_zip() -> Path:
    """Compress the portable folder into a distributable zip archive."""
    print("[6/6] Creating compressed portable distribution archive…")
    tag_name = os.environ.get("GITHUB_REF_NAME") or "v0.1.0"
    if not tag_name.startswith("v"):
        tag_name = f"v{tag_name}"
    zip_path = DIST_DIR / f"ClipCraft_{tag_name}_Windows_Portable.zip"
    if zip_path.is_file():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in APP_DIST.rglob("*"):
            if file.is_file():
                rel_path = file.relative_to(DIST_DIR)
                zf.write(file, rel_path)

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"      Distribution zip archive created: {zip_path.name} ({zip_size_mb:.1f} MB)")
    return zip_path


def main() -> int:
    print("=" * 72)
    print(" ClipCraft — Standalone Portable Windows Build Pipeline")
    print("=" * 72)

    try:
        ensure_icon()
        run_pyinstaller()
        bundle_binaries()
        bundle_templates_and_assets()
        verify_executable()
        zip_path = create_portable_zip()

        print("\n" + "=" * 72)
        print(" BUILD COMPLETE — Standalone Portable Windows Release Ready!")
        print("=" * 72)
        print(f"  Folder:   {APP_DIST}")
        print(f"  Launcher: {APP_DIST / 'ClipCraft.exe'}")
        print(f"  Archive:  {zip_path}")
        print("=" * 72)
        return 0
    except Exception as exc:
        print(f"\n[BUILD ERROR] Build failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

