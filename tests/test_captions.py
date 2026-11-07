from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QApplication

from clipcraft.captions import (
    CaptionWord,
    CaptionCue,
    CaptionStyle,
    group_words_into_cues,
    hex_to_ass_bgr,
    format_ass_timestamp,
    format_srt_timestamp,
    export_to_ass,
    export_to_srt,
    is_cuda_usable,
)
from clipcraft.preview import render_caption_overlay
from clipcraft.renderer import build_filter_complex
from clipcraft.gui.caption_dialog import CaptionStudioDialog


class TestCaptionsEngine(unittest.TestCase):
    """Test suite for AI Auto-Captions, word-by-word animation, ASS/SRT generation, and styling."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_caption_word_and_cue_serialization(self):
        w1 = CaptionWord("CLUTCH", 1.25, 1.85, 0.98)
        w2 = CaptionWord("ACE", 1.90, 2.45, 0.99)
        cue = CaptionCue(1.25, 2.45, "CLUTCH ACE", [w1, w2])

        d = cue.to_dict()
        self.assertEqual(d["start"], 1.25)
        self.assertEqual(d["end"], 2.45)
        self.assertEqual(len(d["words"]), 2)

        restored = CaptionCue.from_dict(d)
        self.assertEqual(restored.text, "CLUTCH ACE")
        self.assertEqual(len(restored.words), 2)
        self.assertEqual(restored.words[0].word, "CLUTCH")

    def test_group_words_into_cues_chunking(self):
        words = [
            CaptionWord("Hey", 0.0, 0.3),
            CaptionWord("guys", 0.35, 0.6),
            CaptionWord("watch", 0.65, 0.9),
            CaptionWord("this", 0.95, 1.2),
            CaptionWord("insane", 1.25, 1.6),
            CaptionWord("clutch!", 1.65, 2.1),  # Ends with !
            CaptionWord("He", 3.0, 3.3),         # Pause > 0.35s
            CaptionWord("was", 3.35, 3.6),
            CaptionWord("defusing", 3.65, 4.1),
        ]
        cues = group_words_into_cues(words, max_words=4, max_duration=2.5, pause_threshold=0.35)

        self.assertGreaterEqual(len(cues), 3)
        # First cue has at most 4 words
        self.assertLessEqual(len(cues[0].words), 4)
        # "clutch!" ends with ! so it triggers cue boundary
        all_texts = [c.text for c in cues]
        self.assertTrue(any("insane clutch!" in t for t in all_texts))
        # "He was defusing" is after a natural pause
        self.assertTrue(any("defusing" in t for t in all_texts))

    def test_hex_to_ass_bgr(self):
        # White #FFFFFF -> &H00FFFFFF&
        self.assertEqual(hex_to_ass_bgr("#FFFFFF"), "&H00FFFFFF&")
        # Neon Yellow #FFE600 (R=FF, G=E6, B=00) -> BGR is &H0000E6FF&
        self.assertEqual(hex_to_ass_bgr("#FFE600"), "&H0000E6FF&")
        # Neon Green #00FF66 (R=00, G=FF, B=66) -> BGR is &H0066FF00&
        self.assertEqual(hex_to_ass_bgr("#00FF66"), "&H0066FF00&")

    def test_timestamp_formatting(self):
        # ASS centiseconds: 12.345s -> 0:00:12.35
        self.assertEqual(format_ass_timestamp(12.345), "0:00:12.35")
        self.assertEqual(format_ass_timestamp(65.1), "0:01:05.10")

        # SRT milliseconds: 12.345s -> 00:00:12,345
        self.assertEqual(format_srt_timestamp(12.345), "00:00:12,345")
        self.assertEqual(format_srt_timestamp(3661.5), "01:01:01,500")

    def test_export_to_ass_with_karaoke_highlight(self):
        w1 = CaptionWord("INSANE", 1.0, 1.4)
        w2 = CaptionWord("HEADSHOT", 1.45, 1.9)
        cues = [CaptionCue(1.0, 1.9, "INSANE HEADSHOT", [w1, w2])]
        style = CaptionStyle(
            font_family="Impact",
            font_size=56,
            primary_color="#FFFFFF",
            highlight_color="#FFE600",
            stroke_color="#000000",
            stroke_width=8,
            position_y=0.70,
            uppercase=True,
            word_highlight=True,
        )

        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
            ass_path = Path(f.name)

        try:
            export_to_ass(cues, ass_path, style, canvas_w=1080, canvas_h=1920)
            self.assertTrue(ass_path.is_file())
            content = ass_path.read_text(encoding="utf-8")

            # Check ASS header
            self.assertIn("PlayResX: 1080", content)
            self.assertIn("PlayResY: 1920", content)
            self.assertIn("Style: Default,Impact,56", content)

            # Check safe zone margin (at 70% Y, MarginV = (1.0 - 0.70)*1920 = 576)
            self.assertIn(",576,1", content)

            # Check karaoke color tags
            self.assertIn(r"{\c&H0000E6FF&}INSANE{\c&H00FFFFFF&}", content)
            self.assertIn(r"{\c&H0000E6FF&}HEADSHOT{\c&H00FFFFFF&}", content)
        finally:
            if ass_path.is_file():
                ass_path.unlink()

    def test_export_to_srt(self):
        cues = [
            CaptionCue(1.0, 2.0, "First cue"),
            CaptionCue(2.5, 4.0, "Second cue"),
        ]
        with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as f:
            srt_path = Path(f.name)

        try:
            export_to_srt(cues, srt_path, uppercase=True)
            self.assertTrue(srt_path.is_file())
            content = srt_path.read_text(encoding="utf-8")
            self.assertIn("1\n00:00:01,000 --> 00:00:02,000\nFIRST CUE", content)
            self.assertIn("2\n00:00:02,500 --> 00:00:04,000\nSECOND CUE", content)
        finally:
            if srt_path.is_file():
                srt_path.unlink()

    def test_render_caption_overlay_preview(self):
        w1 = CaptionWord("VICTORY", 1.0, 2.0)
        w2 = CaptionWord("ROYALE", 2.05, 3.0)
        cues = [CaptionCue(1.0, 3.0, "VICTORY ROYALE", [w1, w2])]
        style = CaptionStyle(
            font_size=48,
            primary_color="#FFFFFF",
            highlight_color="#FFE600",
            position_y=0.70,
        )

        # Before cue start -> None
        img, x, y = render_caption_overlay(cues, 0.5, 360, 640, style)
        self.assertIsNone(img)

        # Inside first word (1.5s) -> Returns valid RGBA image centered in safe zone
        img, x, y = render_caption_overlay(cues, 1.5, 360, 640, style)
        self.assertIsNotNone(img)
        self.assertEqual(img.shape[2], 4)  # RGBA
        self.assertGreater(x, 0)
        # Position Y near 70% of 640 (~448)
        self.assertAlmostEqual(y + img.shape[0] // 2, int(640 * 0.70), delta=10)

    def test_filter_complex_with_captions(self):
        w1 = CaptionWord("HEADSHOT", 0.5, 1.5)
        config = {
            "canvas": {"width": 1080, "height": 1920, "fps": 60},
            "background": {"blur": 15, "brightness": 0.0, "saturation": 1.0},
            "layers": {
                "background": {"kind": "background", "z": 0, "visible": True},
                "main": {"kind": "video", "rect": [0, 0.25, 1, 0.5], "crop": [0, 0, 1, 1], "z": 10, "visible": True},
            },
            "captions": {
                "enabled": True,
                "cues": [CaptionCue(0.5, 1.5, "HEADSHOT", [w1]).to_dict()],
                "style": CaptionStyle().to_dict(),
            },
        }
        video_info = {"width": 1920, "height": 1080, "fps": 60.0}
        graph, overlays = build_filter_complex(config, Path("dummy.json"), video_info)

        # Verify subtitles filter was injected
        self.assertIn("subtitles=", graph)
        self.assertIn(".ass", graph)

    def test_caption_studio_dialog_instantiation(self):
        captions_cfg = {
            "enabled": True,
            "cues": [
                {
                    "start": 1.0,
                    "end": 2.5,
                    "text": "AMAZING PLAY",
                    "words": [
                        {"word": "AMAZING", "start": 1.0, "end": 1.7},
                        {"word": "PLAY", "start": 1.8, "end": 2.5},
                    ],
                }
            ],
            "style": {
                "font_size": 60,
                "highlight_color": "#00FF66",
                "position_y": 0.70,
            },
        }
        dlg = CaptionStudioDialog(None, video_path=None, captions_config=captions_cfg)
        self.assertTrue(dlg.enable_check.isChecked())
        self.assertEqual(dlg.table.rowCount(), 1)
        self.assertEqual(dlg.size_spin.value(), 60)
        self.assertEqual(dlg.pos_slider.value(), 70)

        out_cfg = dlg.get_captions_config()
        self.assertTrue(out_cfg["enabled"])
        self.assertEqual(len(out_cfg["cues"]), 1)
        dlg.close()

    def test_is_cuda_usable_boolean(self):
        usable = is_cuda_usable()
        self.assertIsInstance(usable, bool)


if __name__ == "__main__":
    unittest.main()
