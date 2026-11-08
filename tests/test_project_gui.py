from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog

from clipcraft.gui import ClipCraftWindow
from clipcraft.project import load_project


class TestProjectGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, video: Path | None = None) -> ClipCraftWindow:
        win = ClipCraftWindow(None, "valorant")
        if video is not None:
            win.video_path = str(video)
            win.video_info = {
                "duration": 10.0, "fps": 30.0, "width": 1920, "height": 1080,
                "has_audio": True,
            }
        return win

    def test_autosave_writes_a_sidecar_and_restores_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clutch.mp4"
            win = self._window(video)
            try:
                win._cut_regions = [(3.0, 4.0)]
                win.in_spin.setValue(1.0)
                win.out_spin.setValue(8.0)
                win.playhead = 2.5
                win.audio_config = {"bgm_path": "song.mp3", "bgm_volume": 0.4}
                win.config["captions"] = {"enabled": True, "cues": [], "style": {}}

                with mock.patch("clipcraft.gui.main_window.save_state"), \
                     mock.patch("clipcraft.gui.main_window.load_state", return_value={}):
                    saved = win._save_project(silent=True)
                self.assertIsNotNone(saved)
                self.assertTrue(saved.is_file())
                self.assertEqual(saved.name, "clutch.clipcraft")

                data = load_project(saved)
                self.assertEqual(data["in"], 1.0)
                self.assertEqual(data["out"], 8.0)
                self.assertEqual(data["cuts"], [(3.0, 4.0)])
                self.assertEqual(data["audio"]["bgm_volume"], 0.4)
                self.assertTrue(data["captions"]["enabled"])
                self.assertAlmostEqual(data["playhead"], 2.5)
            finally:
                win.close()

            # A fresh window for the same recording restores the sidecar.
            restored = self._window(video)
            try:
                with mock.patch("clipcraft.gui.main_window.save_state"), \
                     mock.patch("clipcraft.gui.main_window.load_state", return_value={}):
                    restored._restore_project_for_video(video)
                self.assertEqual(restored._cut_regions, [(3.0, 4.0)])
                self.assertAlmostEqual(restored.in_spin.value(), 1.0)
                self.assertAlmostEqual(restored.out_spin.value(), 8.0)
                self.assertEqual(restored.project_path, saved)
            finally:
                restored.close()

    def test_corrupt_sidecar_does_not_block_the_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            (Path(tmp) / "clip.clipcraft").write_text("{not json", encoding="utf-8")
            win = self._window(video)
            try:
                with mock.patch("clipcraft.gui.main_window.save_state"):
                    win._restore_project_for_video(video)  # must not raise
                self.assertIsNone(win.project_path)
            finally:
                win.close()

    def test_trim_edits_mark_the_project_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = self._window(Path(tmp) / "clip.mp4")
            try:
                win._project_dirty = False
                win._on_in_out_changed(0.0)
                self.assertTrue(win._project_dirty)
            finally:
                win.close()

    def test_restoring_suppresses_autosave(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = self._window(Path(tmp) / "clip.mp4")
            try:
                win._project_dirty = False
                win._suppress_project_autosave = True
                win._mark_project_dirty()
                self.assertFalse(win._project_dirty)
            finally:
                win.close()

    def test_split_dialog_receives_detected_cuts(self):
        from clipcraft.gui import main_window as mw

        with tempfile.TemporaryDirectory() as tmp:
            win = self._window(Path(tmp) / "clip.mp4")
            captured: dict = {}

            class FakeDialog:
                def __init__(self, parent, video, info, cuts, in_point, out_point):
                    captured["cuts"] = list(cuts)
                    captured["in"] = in_point
                    captured["out"] = out_point

                def exec(self):
                    return QDialog.DialogCode.Rejected

            try:
                win._cut_regions = [(5.0, 6.0)]
                win.in_spin.setValue(0.0)
                win.out_spin.setValue(10.0)
                with mock.patch.object(mw, "SplitEditorDialog", FakeDialog):
                    win.open_split_dialog(extra_cuts=[(2.0, 3.0)])
                self.assertEqual(captured["cuts"], [(2.0, 3.0), (5.0, 6.0)])
                self.assertAlmostEqual(captured["in"], 0.0)
                self.assertAlmostEqual(captured["out"], 10.0)
            finally:
                win.close()

    def test_save_template_as_bundles_images(self):
        from clipcraft.gui import main_window as mw
        import clipcraft.template_bundle as bundle_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates = root / "templates"
            templates.mkdir()
            image = root / "logo.png"
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(image)

            win = self._window(Path(tmp) / "clip.mp4")
            try:
                win.config["layers"]["bundle_logo"] = {
                    "kind": "image", "asset": str(image), "rect": [0, 0, 0.2, 0.2],
                    "fit": "contain", "opacity": 1.0, "z": 30, "visible": True,
                }
                with mock.patch.object(bundle_module, "TEMPLATES_DIR", templates), \
                     mock.patch.object(mw.QInputDialog, "getText", return_value=("Smoke Layout", True)), \
                     mock.patch.object(mw, "save_state"), \
                     mock.patch.object(mw, "load_state", return_value={}):
                    win.save_template_as()

                self.assertEqual(win.game, "smoke_layout")
                self.assertTrue(win.config_path.is_file())
                self.assertTrue((templates / "assets" / "smoke_layout" / "logo.png").is_file())
                saved = json.loads(win.config_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    saved["layers"]["bundle_logo"]["asset"],
                    "assets/smoke_layout/logo.png",
                )
            finally:
                win.close()

    def test_forget_project_removes_the_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            sidecar = Path(tmp) / "clip.clipcraft"
            sidecar.write_text("{}", encoding="utf-8")
            win = self._window(video)
            try:
                win.project_path = sidecar
                with mock.patch("clipcraft.gui.main_window.QMessageBox.question",
                                return_value=__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes):
                    win._forget_project()
                self.assertFalse(sidecar.exists())
                self.assertIsNone(win.project_path)
            finally:
                win.close()


if __name__ == "__main__":
    unittest.main()
