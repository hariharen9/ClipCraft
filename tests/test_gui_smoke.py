from __future__ import annotations

import unittest
import numpy as np
from PySide6.QtWidgets import QApplication

from clipcraft.gui import (
    ClipCraftWindow,
    BatchWindow,
    TransportWidget,
    LayerInspectorWidget,
    VisualSourceCropDialog,
    AudioStudioDialog,
    CaptionStudioDialog,
)


class TestGuiSmoke(unittest.TestCase):
    """Smoke test for GUI components running headlessly."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_transport_widget(self):
        transport = TransportWidget()
        self.assertIsNotNone(transport.play_button)
        self.assertIsNotNone(transport.position_slider)

        transport.set_playing(True, 1)
        self.assertIn("Pause", transport.play_button.text())

        transport.set_playing(True, -1)
        self.assertIn("Rewind", transport.play_button.text())

        transport.set_playing(False)
        self.assertIn("Play", transport.play_button.text())

    def test_transport_in_out_signal_carries_value(self):
        """Regression: Signal() declared without args broke every IN/OUT spinbox edit."""
        transport = TransportWidget()
        received: list[float] = []
        transport.in_out_changed.connect(received.append)

        transport.in_spin.setValue(3.5)
        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(received[0], 3.5)

        transport.out_spin.setValue(12.25)
        self.assertEqual(len(received), 2)
        self.assertAlmostEqual(received[1], 12.25)

    def test_event_filter_tolerates_non_widget_receivers(self):
        """Regression: the app-level filter receives QWindow/QGraphicsScene and crashed on isAncestorOf."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent, QWindow

        win = ClipCraftWindow(None, "valorant")
        win.isActiveWindow = lambda: True
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)

        try:
            self.assertFalse(win.eventFilter(QWindow(), event))
            self.assertFalse(win.eventFilter(win.scene, event))
        finally:
            win.close()

    def test_event_filter_still_handles_child_widget_keys(self):
        """The parentage guard must not stop real widget hotkeys from reaching the editor."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        win = ClipCraftWindow(None, "valorant")
        win.isActiveWindow = lambda: True
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_I, Qt.KeyboardModifier.NoModifier)

        try:
            self.assertTrue(win.eventFilter(win.preview_view, event))
            # 'I' sets the IN point at the playhead; that flows through the fixed signal.
            self.assertAlmostEqual(win.in_spin.value(), win.playhead, places=3)
        finally:
            win.close()

    def test_layer_inspector_widget(self):
        inspector = LayerInspectorWidget()
        self.assertIsNotNone(inspector.layer_stack)
        self.assertIn("x", inspector.geom_fields)
        self.assertIn("y", inspector.geom_fields)
        self.assertIn("w", inspector.geom_fields)
        self.assertIn("h", inspector.geom_fields)
        self.assertIn("x", inspector.crop_fields)

        inspector.set_undo_redo_enabled(True, False)
        self.assertTrue(inspector.undo_button.isEnabled())
        self.assertFalse(inspector.redo_button.isEnabled())

    def test_clipcraft_window_instantiation(self):
        win = ClipCraftWindow(None, "valorant")
        self.assertIsNotNone(win.transport)
        self.assertIsNotNone(win.inspector)
        self.assertEqual(win.game, "valorant")
        self.assertGreater(len(win.config["layers"]), 0)

        # Test selecting a layer
        win.layer_stack.list_widget.setCurrentRow(0)
        active = win._active_layer_name()
        self.assertIsNotNone(active)

    def test_batch_window_instantiation(self):
        batch = BatchWindow("valorant")
        self.assertIsNotNone(batch._job_list)
        self.assertIsNotNone(batch._render_btn)
        self.assertEqual(batch._game, "valorant")

    def test_visual_crop_dialog(self):
        dummy_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        applied = []
        dlg = VisualSourceCropDialog(
            None, dummy_frame, "killfeed", [0.1, 0.1, 0.5, 0.5], lambda c: applied.append(c),
        )
        self.assertEqual(dlg.src_w, 1920)
        self.assertEqual(dlg.src_h, 1080)
        dlg._apply()
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(applied[0]), 4)

    def test_audio_studio_dialog(self):
        cfg = {
            "bgm_path": None,
            "bgm_volume": 0.45,
            "gameplay_volume": 0.85,
            "bgm_start": 12.5,
            "bgm_end": 45.0,
            "auto_ducking": True,
            "fade_in": 0.5,
            "fade_out": 0.5,
        }
        dlg = AudioStudioDialog(None, audio_config=cfg, clip_duration=30.0)
        self.assertEqual(dlg.bgm_slider.value(), 45)
        self.assertEqual(dlg.game_slider.value(), 85)
        self.assertAlmostEqual(dlg.bgm_start_spin.value(), 12.5)
        self.assertAlmostEqual(dlg.bgm_end_spin.value(), 45.0)
        self.assertTrue(dlg.ducking_check.isChecked())

        res = dlg.get_audio_config()
        self.assertEqual(res["bgm_volume"], 0.45)
        self.assertEqual(res["gameplay_volume"], 0.85)
        self.assertEqual(res["bgm_start"], 12.5)
        self.assertEqual(res["bgm_end"], 45.0)

        # Check spinbox widths prevent text truncation
        self.assertGreaterEqual(dlg.fade_in_spin.maximumWidth(), 110)
        self.assertGreaterEqual(dlg.fade_out_spin.maximumWidth(), 110)
        self.assertEqual(dlg.fade_in_spin.decimals(), 1)
        self.assertEqual(dlg.fade_out_spin.decimals(), 1)
        self.assertGreaterEqual(dlg.bgm_start_spin.maximumWidth(), 110)
        self.assertGreaterEqual(dlg.bgm_end_spin.maximumWidth(), 125)
        dlg.close()

    def test_audio_studio_scrub_and_audition_position(self):
        cfg = {
            "bgm_path": None,
            "bgm_volume": 0.5,
            "gameplay_volume": 1.0,
            "bgm_start": 5.0,
            "bgm_end": 50.0,
        }
        dlg = AudioStudioDialog(None, audio_config=cfg, clip_duration=60.0)
        dlg.file_edit.setText("dummy_track.mp3")
        dlg._bgm_duration = 60.0

        # Simulate user scrubbing to 25.0 seconds (25 / 60 * 10000 = ~4166)
        dlg.scrubber.setValue(4166)
        dlg._on_scrubber_moved(4166)

        # Starting audition must play from the scrubbed position, NOT reset to start_spin (5.0s)
        dlg._start_audition()
        self.assertAlmostEqual(dlg._last_audition_pos_sec, 25.0, delta=0.2)
        dlg._stop_audition()
        dlg.close()

    def test_caption_studio_dialog_smoke(self):
        dlg = CaptionStudioDialog(None)
        self.assertIsNotNone(dlg.transcribe_btn)
        self.assertIsNotNone(dlg.highlight_combo)
        self.assertIsNotNone(dlg.pos_slider)
        self.assertIsNotNone(dlg.table)

        # Check friendly language names
        eng_idx = dlg.lang_combo.findText("English")
        self.assertGreaterEqual(eng_idx, 0)
        self.assertEqual(dlg.lang_combo.itemData(eng_idx), "en")

        auto_idx = dlg.lang_combo.findText("Auto-Detect")
        self.assertGreaterEqual(auto_idx, 0)
        self.assertIsNone(dlg.lang_combo.itemData(auto_idx))

        # Check progress bar height prevents clipped % text
        self.assertGreaterEqual(dlg.progress_bar.maximumHeight(), 18)

        # Test progress display formatting
        dlg._on_worker_progress(0.45, "Transcribing segment 2")
        self.assertEqual(dlg.progress_bar.value(), 45)
        self.assertIn("45%", dlg.status_lbl.text())

        # Test finished display shows friendly language name
        dlg._on_worker_finished([], "en")
        self.assertIn("English", dlg.status_lbl.text())

        dlg.close()

    def test_app_icon_and_loading_overlay(self):
        from clipcraft.gui.constants import get_app_icon
        from clipcraft.gui.main_window import ImportLoadingOverlay

        icon = get_app_icon()
        self.assertFalse(icon.isNull())

        overlay = ImportLoadingOverlay()
        self.assertFalse(overlay.isVisible())
        overlay.show_loading("test_clip.mp4", "Analyzing streams…")
        self.assertTrue(overlay.isVisible())
        self.assertIn("test_clip.mp4", overlay.filename_lbl.text())
        overlay.set_status("Decoding initial frame…")
        self.assertIn("initial frame", overlay.status_lbl.text())
        overlay.hide_loading()
        self.assertFalse(overlay.isVisible())


if __name__ == "__main__":
    unittest.main()

