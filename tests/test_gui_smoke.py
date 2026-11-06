from __future__ import annotations

import unittest
import numpy as np
from PySide6.QtWidgets import QApplication

from clipcraft.gui import (
    ClipCraftWindow,
    FasTrackWindow,
    BatchWindow,
    TransportWidget,
    LayerInspectorWidget,
    VisualSourceCropDialog,
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

        # Verify backward-compatibility alias
        self.assertIs(FasTrackWindow, ClipCraftWindow)

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


if __name__ == "__main__":
    unittest.main()

