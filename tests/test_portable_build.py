from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from clipcraft.config import APP_DIR, BUNDLE_DIR, _ensure_templates_dir, TEMPLATES_DIR
from clipcraft.renderer import find_ffmpeg, find_ffprobe


class TestPortableBuild(unittest.TestCase):
    """Test standalone build configurations, bundled templates, and executable launcher."""

    def test_bundle_paths_and_templates_dir(self):
        self.assertTrue(APP_DIR.is_dir())
        self.assertTrue(BUNDLE_DIR.is_dir())
        tmpl = _ensure_templates_dir()
        self.assertTrue(tmpl.is_dir())
        self.assertTrue((tmpl / "valorant.json").is_file())

    def test_find_ffmpeg_and_ffprobe(self):
        # find_ffmpeg must return a valid executable path
        ffmpeg_bin = find_ffmpeg()
        self.assertTrue(Path(ffmpeg_bin).is_file())

        ffprobe_bin = find_ffprobe()
        self.assertTrue(Path(ffprobe_bin).is_file())

    def test_build_spec_and_script_exist(self):
        root = Path(__file__).resolve().parent.parent
        self.assertTrue((root / "clipcraft.spec").is_file())
        self.assertTrue((root / "build_portable.py").is_file())
        self.assertTrue((root / "build_portable.bat").is_file())
        self.assertTrue((root / "clipcraft.ico").is_file())

    def test_compiled_executable_smoke(self):
        root = Path(__file__).resolve().parent.parent
        exe = root / "dist" / "ClipCraft" / "ClipCraft.exe"
        if not exe.is_file():
            self.skipTest("dist/ClipCraft/ClipCraft.exe not built yet")

        proc = subprocess.run([str(exe), "--help"], capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0)
        stdout_text = proc.stdout.decode("utf-8", errors="replace")
        self.assertIn("ClipCraft", stdout_text)


if __name__ == "__main__":
    unittest.main()
