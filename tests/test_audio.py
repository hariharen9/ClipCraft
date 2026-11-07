from __future__ import annotations

import tempfile
import unittest
import importlib.util
from pathlib import Path

from clipcraft.renderer import build_audio_filter_graph, build_ffmpeg_command

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("clipcraft_script", ROOT / "clipcraft.py")
clipcraft_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clipcraft_script)
build_parser = clipcraft_script.build_parser


class TestAudioEngine(unittest.TestCase):
    """Test the Audio & Background Music (BGM) Engine, including ducking and fading."""

    def test_build_audio_filter_graph_gameplay_only(self):
        video_info = {"has_audio": True}
        duration = 10.0
        audio_cfg = {
            "gameplay_volume": 1.0,
            "fade_in": 0.5,
            "fade_out": 0.5,
        }
        graph, has_audio = build_audio_filter_graph(video_info, duration, audio_cfg, bgm_input_index=None)
        self.assertTrue(has_audio)
        self.assertIn("[0:a]", graph)
        self.assertIn("volume=1.0000", graph)
        self.assertIn("afade=t=in:ss=0:d=0.5000", graph)
        self.assertIn("afade=t=out:st=9.5000:d=0.5000", graph)
        self.assertIn("[outa]", graph)

    def test_build_audio_filter_graph_with_bgm_and_ducking(self):
        video_info = {"has_audio": True}
        duration = 15.0
        audio_cfg = {
            "gameplay_volume": 1.2,
            "bgm_volume": 0.35,
            "auto_ducking": True,
            "ducking_threshold": 0.125,
            "ducking_ratio": 4.0,
            "fade_in": 0.5,
            "fade_out": 0.5,
        }
        graph, has_audio = build_audio_filter_graph(video_info, duration, audio_cfg, bgm_input_index=2)
        self.assertTrue(has_audio)
        self.assertIn("[0:a]", graph)
        self.assertIn("[2:a]", graph)
        self.assertIn("asplit=2[agp_mix][agp_sc]", graph)
        self.assertIn("sidechaincompress=threshold=0.1250:ratio=4.00", graph)
        self.assertIn("amix=inputs=2:duration=first:dropout_transition=2:normalize=0", graph)
        self.assertIn("afade=t=in:ss=0:d=0.5000", graph)
        self.assertIn("afade=t=out:st=14.5000:d=0.5000", graph)
        self.assertIn("[outa]", graph)

    def test_build_audio_filter_graph_no_ducking(self):
        video_info = {"has_audio": True}
        duration = 8.0
        audio_cfg = {
            "gameplay_volume": 1.0,
            "bgm_volume": 0.25,
            "auto_ducking": False,
            "fade_in": 0.4,
            "fade_out": 0.4,
        }
        graph, has_audio = build_audio_filter_graph(video_info, duration, audio_cfg, bgm_input_index=1)
        self.assertTrue(has_audio)
        self.assertNotIn("sidechaincompress", graph)
        self.assertNotIn("asplit", graph)
        self.assertIn("[agp_raw][abgm_raw]amix=", graph)
        self.assertIn("afade=t=in:ss=0:d=0.4000", graph)
        self.assertIn("afade=t=out:st=7.6000:d=0.4000", graph)
        self.assertIn("[outa]", graph)

    def test_build_audio_filter_graph_no_audio(self):
        video_info = {"has_audio": False}
        graph, has_audio = build_audio_filter_graph(video_info, 10.0, {}, bgm_input_index=None)
        self.assertFalse(has_audio)
        self.assertEqual(graph, "")

    def test_build_audio_filter_graph_bgm_only(self):
        video_info = {"has_audio": False}
        duration = 6.0
        audio_cfg = {
            "bgm_volume": 0.4,
            "fade_in": 0.5,
            "fade_out": 0.5,
        }
        graph, has_audio = build_audio_filter_graph(video_info, duration, audio_cfg, bgm_input_index=1)
        self.assertTrue(has_audio)
        self.assertNotIn("[0:a]", graph)
        self.assertIn("[1:a]", graph)
        self.assertIn("volume=0.4000", graph)
        self.assertIn("afade=t=in:ss=0:d=0.5000", graph)
        self.assertIn("afade=t=out:st=5.5000:d=0.5000", graph)
        self.assertIn("[outa]", graph)

    def test_fade_clamping_for_short_clips(self):
        video_info = {"has_audio": True}
        duration = 0.6  # Half duration is 0.3s
        audio_cfg = {
            "fade_in": 0.5,
            "fade_out": 0.5,
        }
        graph, has_audio = build_audio_filter_graph(video_info, duration, audio_cfg, bgm_input_index=None)
        self.assertTrue(has_audio)
        # Fades should be clamped to 0.3000s each
        self.assertIn("afade=t=in:ss=0:d=0.3000", graph)
        self.assertIn("afade=t=out:st=0.3000:d=0.3000", graph)

    def test_cli_audio_parser(self):
        parser = build_parser()
        args = parser.parse_args([
            "clip.mp4",
            "--in", "0",
            "--out", "10",
            "--bgm", "music.mp3",
            "--bgm-volume", "0.45",
            "--gameplay-volume", "1.1",
            "--no-ducking",
            "--audio-fade", "0.8",
        ])
        self.assertEqual(args.bgm, "music.mp3")
        self.assertEqual(args.bgm_volume, 0.45)
        self.assertEqual(args.gameplay_volume, 1.1)
        self.assertTrue(args.no_ducking)
        self.assertEqual(args.audio_fade, 0.8)


if __name__ == "__main__":
    unittest.main()
