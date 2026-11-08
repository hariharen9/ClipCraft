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

    def test_split_editor_dialog_cuts_segments(self):
        from clipcraft.gui import SplitEditorDialog

        dlg = SplitEditorDialog(
            None, "", {"duration": 8.0, "fps": 30.0},
            cuts=[(2.0, 3.0)], in_point=0.0, out_point=8.0,
        )
        try:
            # Existing cut arrives as a removed segment with split marks on its edges.
            self.assertEqual(dlg.timeline.segments(), [(0.0, 2.0), (2.0, 3.0), (3.0, 8.0)])
            self.assertTrue(dlg.timeline.segment_removed(1))
            self.assertAlmostEqual(dlg.result_data()["duration"], 7.0, places=6)

            # Delete the first segment: it merges with the existing cut.
            dlg.timeline.selected = 0
            dlg.delete_selected_segment()
            self.assertEqual(dlg.timeline.cuts(), [(0.0, 3.0)])
            self.assertAlmostEqual(dlg.result_data()["duration"], 5.0, places=6)

            dlg.restore_all()
            self.assertEqual(dlg.timeline.cuts(), [])
            self.assertAlmostEqual(dlg.result_data()["duration"], 8.0, places=6)
        finally:
            dlg.close()

    def test_split_editor_in_out_handles(self):
        from clipcraft.gui import SplitEditorDialog

        dlg = SplitEditorDialog(None, "", {"duration": 10.0, "fps": 25.0})
        try:
            dlg.timeline.playhead = 2.0
            dlg.set_in_here()
            dlg.timeline.playhead = 7.5
            dlg.set_out_here()
            data = dlg.result_data()
            self.assertAlmostEqual(data["in"], 2.0)
            self.assertAlmostEqual(data["out"], 7.5)
            self.assertAlmostEqual(data["duration"], 5.5)

            # A split that is not inside IN/OUT is rejected.
            dlg.timeline.playhead = 1.0
            self.assertFalse(dlg.timeline.add_split(1.0))
        finally:
            dlg.close()

    def test_main_window_cut_timeline_helpers(self):
        win = ClipCraftWindow(None, "valorant")
        try:
            win.video_info = {"duration": 10.0, "fps": 30.0}
            win._cut_regions = [(3.0, 5.0)]
            win.in_spin.blockSignals(True)
            win.out_spin.blockSignals(True)
            win.in_spin.setValue(0.0)
            win.out_spin.setValue(10.0)
            win.in_spin.blockSignals(False)
            win.out_spin.blockSignals(False)

            self.assertAlmostEqual(win._kept_duration(), 8.0)
            self.assertAlmostEqual(win._timeline_total(), 8.0)
            # 4.0s of source sits 3.0s into the edited timeline of 8.0s.
            self.assertEqual(win._source_to_slider(4.0), 3750)
            self.assertAlmostEqual(win._slider_to_source(3750), 3.0, places=6)

            win._apply_split_edit({"in": 0.0, "out": 10.0, "cuts": []})
            self.assertEqual(win._cut_regions, [])
            self.assertAlmostEqual(win._kept_duration(), 10.0)
        finally:
            win.close()

    def test_timeline_paint_keeps_segments_after_a_cut(self):
        """Regression: a leftover red brush made drawRect() flood kept segments."""
        from PySide6.QtGui import QColor
        from clipcraft.gui.split_dialog import SplitTimeline

        tl = SplitTimeline(40.0)
        tl.in_point, tl.out_point = 2.0, 36.0
        tl.removed = [(10.0, 14.0)]
        tl.boundaries = [10.0, 14.0]
        tl.resize(800, 98)
        image = tl.grab().toImage()

        kept = image.pixelColor(int(tl._x_for(30.0)), tl.BAR_TOP + tl.BAR_HEIGHT // 2)
        cut = image.pixelColor(int(tl._x_for(12.0)), tl.BAR_TOP + tl.BAR_HEIGHT // 2)
        self.assertEqual(kept.name().lower(), "#2f4a66")
        self.assertNotEqual(cut.name().lower(), "#2f4a66")

    def test_inspector_fade_controls_roundtrip(self):
        inspector = LayerInspectorWidget()
        self.assertAlmostEqual(inspector.fade_in_spin.value(), 0.5)
        self.assertAlmostEqual(inspector.fade_out_spin.value(), 0.5)
        self.assertFalse(inspector.fade_in_spin.isEnabled())

        inspector.set_fade_controls(True, 1.25, 0.75)
        self.assertEqual(inspector.fade_settings(), (True, 1.25, 0.75))
        self.assertTrue(inspector.fade_in_spin.isEnabled())
        self.assertTrue(inspector.fade_out_spin.isEnabled())

        inspector.set_fade_controls(False, 0.5, 0.5)
        self.assertEqual(inspector.fade_settings(), (False, 0.5, 0.5))
        self.assertFalse(inspector.fade_in_spin.isEnabled())

    def test_main_window_layer_fade_factor(self):
        win = ClipCraftWindow(None, "valorant")
        try:
            win.video_info = {"duration": 10.0, "fps": 30.0}
            win._cut_regions = [(3.0, 5.0)]  # edited length becomes 8s
            win.in_spin.blockSignals(True)
            win.out_spin.blockSignals(True)
            win.in_spin.setValue(0.0)
            win.out_spin.setValue(10.0)
            win.in_spin.blockSignals(False)
            win.out_spin.blockSignals(False)

            layer = {"fade_enabled": True, "fade_in": 1.0, "fade_out": 1.0}
            cases = {
                0.0: 0.0,    # first frame: fully transparent
                0.5: 0.5,    # halfway through the fade-in
                2.0: 1.0,    # fully visible
                3.5: 1.0,    # inside a removed region, maps to the kept timeline
                9.5: 0.5,    # halfway through the fade-out
                10.0: 0.0,   # last frame: fully transparent
            }
            for playhead, expected in cases.items():
                win.playhead = playhead
                with self.subTest(playhead=playhead):
                    self.assertAlmostEqual(win._layer_fade_factor(layer), expected, places=6)

            self.assertEqual(win._layer_fade_factor({"fade_enabled": False}), 1.0)

            # Outside the trimmed range the editor view stays neutral.
            win.playhead = 10.0
            win.in_spin.blockSignals(True)
            win.in_spin.setValue(2.0)
            win.in_spin.blockSignals(False)
            win.playhead = 1.0
            self.assertEqual(win._layer_fade_factor(layer), 1.0)
        finally:
            win.close()

    def test_apply_fade_to_all_layers(self):
        win = ClipCraftWindow(None, "valorant")
        try:
            win.inspector.set_fade_controls(True, 0.8, 0.4)
            win._apply_fade_to_all()
            layers = win.config["layers"]
            self.assertGreaterEqual(len(layers), 2)
            for name, layer in layers.items():
                with self.subTest(layer=name):
                    self.assertTrue(layer["fade_enabled"])
                    self.assertAlmostEqual(layer["fade_in"], 0.8)
                    self.assertAlmostEqual(layer["fade_out"], 0.4)

            win.inspector.set_fade_controls(False, 0.0, 0.0)
            win._apply_fade_to_all()
            self.assertFalse(any(layer.get("fade_enabled") for layer in layers.values()))
        finally:
            win.close()

    def test_sidebar_widths_prevent_clipped_labels(self):
        """Regression: a 300px inspector clipped its 392px-wide property rows."""
        from PySide6.QtWidgets import QScrollArea

        win = ClipCraftWindow(None, "valorant")
        try:
            self.assertGreaterEqual(win.inspector.minimumWidth(), 400)
            # The inspector is hosted in a scroll area so short screens can scroll it.
            self.assertIsInstance(win.inspector.parentWidget().parentWidget(), QScrollArea)

            widths = sorted(scroll.minimumWidth() for scroll in win.findChildren(QScrollArea))
            self.assertEqual(widths, [336, 416])

            left_panel = min(win.findChildren(QScrollArea), key=lambda s: s.minimumWidth()).widget()
            self.assertGreaterEqual(left_panel.minimumWidth(), 320)
        finally:
            win.close()

    def test_f11_toggles_fullscreen(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        win = ClipCraftWindow(None, "valorant")
        calls = []
        try:
            win.isActiveWindow = lambda: True
            win._toggle_fullscreen = lambda: calls.append("toggle")
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F11, Qt.KeyboardModifier.NoModifier)
            self.assertTrue(win.eventFilter(win.preview_view, event))
            self.assertEqual(calls, ["toggle"])
        finally:
            win.close()

    def test_batch_preview_matches_main_window_fades(self):
        """Regression: the batch preview ignored fades and disagreed with the render."""
        from clipcraft.gui.batch_window import _layer_fade_factor

        layer = {"fade_enabled": True, "fade_in": 1.0, "fade_out": 1.0}
        self.assertEqual(_layer_fade_factor(layer, None, 10.0), 1.0)
        self.assertAlmostEqual(_layer_fade_factor(layer, 0.0, 10.0), 0.0)
        self.assertAlmostEqual(_layer_fade_factor(layer, 0.5, 10.0), 0.5)
        self.assertAlmostEqual(_layer_fade_factor(layer, 5.0, 10.0), 1.0)
        self.assertAlmostEqual(_layer_fade_factor(layer, 9.5, 10.0), 0.5)
        self.assertEqual(_layer_fade_factor({"fade_enabled": False}, 0.0, 10.0), 1.0)

    def test_batch_preview_darkens_faded_background(self):
        batch = BatchWindow("valorant")
        try:
            batch._config = {
                "background": {"blur": 1, "brightness": 0.0, "saturation": 1.0},
                "layers": {
                    "background": {"kind": "background", "rect": [0, 0, 1, 1], "z": 0,
                                   "visible": True, "fade_enabled": True,
                                   "fade_in": 1.0, "fade_out": 1.0},
                },
            }
            frame = np.full((180, 320, 3), 140, dtype=np.uint8)
            batch._preview_duration = 10.0

            batch._preview_elapsed = 0.0
            batch._display_render_preview(frame)
            faded = batch._render_preview_label.pixmap().toImage().pixelColor(5, 5).getRgb()[0]

            batch._preview_elapsed = 5.0
            batch._display_render_preview(frame)
            bright = batch._render_preview_label.pixmap().toImage().pixelColor(5, 5).getRgb()[0]

            self.assertLess(faded, 10)
            self.assertGreater(bright, 60)
        finally:
            batch.close()

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

