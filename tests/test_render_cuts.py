from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from clipcraft.renderer import build_cut_filter, build_filter_complex, find_ffmpeg

try:  # OpenCV is a hard dependency of the app, but keep the import failure local.
    import cv2
except Exception:  # pragma: no cover - only on a broken install
    cv2 = None


def _base_config(fps: int = 10) -> dict:
    return {
        "version": 1,
        "name": "cuttest",
        "canvas": {"width": 180, "height": 320, "fps": fps, "encoder": "cpu", "quality": 18,
                   "x264_preset": "ultrafast"},
        "background": {"blur": 2, "brightness": 0.0, "saturation": 1.0},
        "layers": {
            "background": {"kind": "background", "rect": [0, 0, 1, 1], "z": 0, "visible": True},
            "main": {"kind": "video", "rect": [0, 0, 1, 1], "crop": [0, 0, 1, 1],
                     "fit": "cover", "z": 10, "visible": True},
        },
    }


class TestCutFilterGraph(unittest.TestCase):
    """Structural checks on the trim/concat prelude (no FFmpeg needed)."""

    def test_no_cuts_keeps_plain_labels(self):
        chains, video, audio = build_cut_filter(0, 10, [], True)
        self.assertEqual(chains, "")
        self.assertEqual((video, audio), ("0:v", "0:a"))

    def test_cuts_outside_the_range_are_ignored(self):
        chains, video, audio = build_cut_filter(2, 8, [(0, 1), (9, 10)], True)
        self.assertEqual(chains, "")
        self.assertEqual((video, audio), ("0:v", "0:a"))

    def test_mid_clip_cut_builds_trim_and_concat(self):
        chains, video, audio = build_cut_filter(0, 10, [(3, 5)], True)
        self.assertEqual(video, "vcut")
        self.assertEqual(audio, "acut")
        self.assertIn("[0:v]trim=end=3.000000,setpts=PTS-STARTPTS[cv0]", chains)
        self.assertIn("[0:v]trim=start=5.000000:end=10.000000,setpts=PTS-STARTPTS[cv1]", chains)
        self.assertIn("[cv0][cv1]concat=n=2:v=1:a=0[vcut]", chains)
        self.assertIn("[ca0][ca1]concat=n=2:v=0:a=1[acut]", chains)

    def test_first_span_omits_start_zero(self):
        # An explicit start=0 can drop the first decoded frame after input seeking.
        chains, _, _ = build_cut_filter(0, 10, [(3, 5)], False)
        self.assertIn("trim=end=3.000000", chains)
        self.assertNotIn("trim=start=0.000000", chains)

    def test_audio_is_omitted_when_the_source_has_none(self):
        chains, _, _ = build_cut_filter(0, 10, [(3, 5)], False)
        self.assertNotIn("atrim", chains)
        self.assertNotIn("acut", chains)

    def test_audio_uses_asetpts(self):
        # Regression: setpts on an audio pad made FFmpeg refuse to link the graph.
        chains, _, _ = build_cut_filter(0, 10, [(3, 5)], True)
        for chain in chains.split(";"):
            if "atrim" in chain:
                self.assertIn("asetpts", chain)
                self.assertNotIn(",setpts=", chain)

    def test_cutting_everything_raises(self):
        with self.assertRaises(ValueError):
            build_cut_filter(0, 10, [(0, 10)], True)

    def test_layout_graph_consumes_the_cut_label(self):
        graph, _ = build_filter_complex(_base_config(), Path("cfg.json"), {}, source_v="vcut")
        self.assertTrue(graph.startswith("[vcut]fps=10,split="))
        self.assertNotIn("[0:v]", graph)


@unittest.skipIf(cv2 is None, "OpenCV not available")
class TestCutRenderEndToEnd(unittest.TestCase):
    """Render a frame-numbered clip and prove the removed frames are gone."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = find_ffmpeg()
        except FileNotFoundError:
            raise unittest.SkipTest("FFmpeg is not available")

    def test_removed_frames_do_not_appear(self):
        from clipcraft.renderer import build_ffmpeg_command, run_render

        fps, size = 10, 64
        with tempfile.TemporaryDirectory(prefix="cc_cuttest_") as tmp:
            work = Path(tmp)
            source = work / "src.mkv"
            # Frame i is a flat grey whose value encodes i, so decoding the output
            # tells us exactly which source frames survived. Step of 4 keeps the
            # brightest frame (8 + 39*4 = 164) inside the 0-255 range.
            frames = [
                np.full((size, size), 8 + i * 4, dtype=np.uint8)
                for i in range(fps * 4)
            ]
            subprocess.run(
                [self.ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo",
                 "-pix_fmt", "gray", "-s", f"{size}x{size}", "-r", str(fps), "-i", "-",
                 "-c:v", "ffv1", "-pix_fmt", "gray", str(source)],
                input=b"".join(frame.tobytes() for frame in frames),
                check=True,
            )

            config = _base_config(fps)
            config_path = work / "cfg.json"
            config_path.write_text(json.dumps(config))
            output = work / "out.mp4"
            cuts = [(1.0, 2.0)]

            _, planned = build_ffmpeg_command(
                source, output, 0.0, 4.0, config, config_path, "cpu", cuts=cuts
            )
            self.assertAlmostEqual(planned, 3.0, places=3)

            run_render(source, output, 0.0, 4.0, config, config_path, "cpu", cuts=cuts)

            capture = cv2.VideoCapture(str(output))
            recovered = []
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                centre = frame[frame.shape[0] // 2, frame.shape[1] // 2, 0]
                recovered.append(round((int(centre) - 8) / 4))
            capture.release()

            expected = list(range(0, 10)) + list(range(20, 40))
            self.assertEqual(len(recovered), len(expected))
            self.assertEqual(recovered, expected)


if __name__ == "__main__":
    unittest.main()
