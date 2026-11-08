from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from clipcraft.anim import (
    center_for_layer,
    keys_for_layer,
    normalize_keys,
    overlay_expressions,
    piecewise_expression,
    rect_center,
    sample,
)
from clipcraft.renderer import build_filter_complex

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


class TestKeys(unittest.TestCase):
    def test_rect_center(self):
        self.assertEqual(rect_center([0.2, 0.4, 0.4, 0.2]), (0.4, 0.5))

    def test_normalize_sorts_clamps_and_dedupes(self):
        keys = normalize_keys([
            {"t": 2.0, "x": 0.8, "y": 0.5},
            {"t": 0.0, "x": -1.0, "y": 2.0},
            {"t": 2.0, "x": 0.9, "y": 0.6},
            {"bad": "key"},
        ])
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], {"t": 0.0, "x": 0.0, "y": 1.0})
        self.assertEqual(keys[1]["x"], 0.9)  # last key at the same instant wins

    def test_normalize_clamps_to_duration(self):
        keys = normalize_keys([{"t": 9.0, "x": 0.5, "y": 0.5}], duration=4.0)
        self.assertEqual(keys[0]["t"], 4.0)

    def test_missing_anim_means_static(self):
        self.assertEqual(keys_for_layer({}), [])
        self.assertEqual(keys_for_layer({"anim": {}}), [])

    def test_sample_before_between_after(self):
        keys = [{"t": 0.0, "x": 0.2, "y": 0.2}, {"t": 2.0, "x": 0.6, "y": 0.8}]
        self.assertEqual(sample(keys, -1.0), (0.2, 0.2))
        self.assertEqual(sample(keys, 5.0), (0.6, 0.8))
        mid = sample(keys, 1.0)
        self.assertAlmostEqual(mid[0], 0.4)
        self.assertAlmostEqual(mid[1], 0.5)

    def test_center_for_layer_falls_back_to_rect(self):
        layer = {"rect": [0.1, 0.2, 0.4, 0.2]}
        center = center_for_layer(layer, 3.0)
        self.assertAlmostEqual(center[0], 0.3)
        self.assertAlmostEqual(center[1], 0.3)


class TestExpressions(unittest.TestCase):
    def test_piecewise_clamps_and_interpolates(self):
        expression = piecewise_expression([(0.0, 10.0), (2.0, 20.0)])
        self.assertIn("if(lt(t,2.000000)", expression)
        self.assertIn("10.000000+", expression)

    def test_single_point_is_constant(self):
        self.assertEqual(piecewise_expression([(1.0, 0.7)]), "0.700000")

    def test_overlay_expressions_need_two_keys(self):
        layer = {"rect": [0.0, 0.0, 0.2, 0.2], "anim": {"keys": [{"t": 0, "x": 0.5, "y": 0.5}]}}
        self.assertIsNone(overlay_expressions(layer, 100, 200, 10.0))

    def test_overlay_expressions_center_the_rect(self):
        layer = {
            "rect": [0.4, 0.4, 0.2, 0.2],
            "anim": {"keys": [
                {"t": 0.0, "x": 0.2, "y": 0.5},
                {"t": 2.0, "x": 0.8, "y": 0.5},
            ]},
        }
        x_expr, y_expr = overlay_expressions(layer, 1000, 2000, 10.0)
        # Half the rect (0.1 normalized) is subtracted so x/y is the top-left corner.
        self.assertIn("*1000-100.00", x_expr)
        self.assertIn("*2000-200.00", y_expr)


class TestAnimatedGraph(unittest.TestCase):
    def _config(self, animated: bool) -> dict:
        layer = {"kind": "image", "asset": "logo.png", "rect": [0.1, 0.1, 0.2, 0.2],
                 "fit": "fill", "opacity": 1.0, "z": 20, "visible": True}
        if animated:
            layer["anim"] = {"keys": [
                {"t": 0.0, "x": 0.2, "y": 0.2},
                {"t": 1.0, "x": 0.8, "y": 0.6},
            ]}
        return {
            "version": 1, "name": "animtest",
            "canvas": {"width": 180, "height": 320, "fps": 10},
            "background": {"blur": 1},
            "layers": {
                "background": {"kind": "background", "rect": [0, 0, 1, 1], "z": 0, "visible": True},
                "main": {"kind": "video", "rect": [0, 0, 1, 1], "crop": [0, 0, 1, 1],
                         "fit": "cover", "z": 10, "visible": True},
                "logo": layer,
            },
        }

    def test_animated_overlay_uses_expressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            logo = Path(tmp) / "logo.png"
            Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(logo)
            config = self._config(True)
            config["layers"]["logo"]["asset"] = str(logo)
            graph, _ = build_filter_complex(config, Path(tmp) / "cfg.json", {}, duration=2.0)
            self.assertIn("overlay=x='", graph)
            self.assertIn("eof_action=pass", graph)

    def test_static_overlay_stays_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            logo = Path(tmp) / "logo.png"
            Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(logo)
            config = self._config(False)
            config["layers"]["logo"]["asset"] = str(logo)
            graph, _ = build_filter_complex(config, Path(tmp) / "cfg.json", {}, duration=2.0)
            self.assertNotIn("overlay=x='", graph)


@unittest.skipIf(cv2 is None or Image is None, "OpenCV/Pillow not available")
class TestAnimatedRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from clipcraft.renderer import find_ffmpeg

        try:
            cls.ffmpeg = find_ffmpeg()
        except FileNotFoundError:
            raise unittest.SkipTest("FFmpeg is not available")

    def test_layer_actually_moves(self):
        from clipcraft.renderer import run_render

        with tempfile.TemporaryDirectory(prefix="cc_anim_") as tmp:
            work = Path(tmp)
            source = work / "black.mp4"
            subprocess.run(
                [self.ffmpeg, "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=black:s=180x320:d=2:r=10",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source)],
                check=True,
            )
            logo = work / "logo.png"
            Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)

            def config(x_keys):
                return {
                    "version": 1, "name": "anim",
                    "canvas": {"width": 180, "height": 320, "fps": 10, "encoder": "cpu",
                               "quality": 18, "x264_preset": "ultrafast"},
                    "background": {"blur": 1, "brightness": 0.0, "saturation": 1.0},
                    "layers": {
                        "background": {"kind": "background", "rect": [0, 0, 1, 1], "z": 0, "visible": True},
                        "main": {"kind": "video", "rect": [0, 0, 1, 1], "crop": [0, 0, 1, 1],
                                 "fit": "cover", "z": 10, "visible": True},
                        "logo": {"kind": "image", "asset": str(logo), "rect": [0.0, 0.4, 0.1, 0.1],
                                 "fit": "fill", "opacity": 1.0, "z": 20, "visible": True,
                                 "anim": {"keys": x_keys}},
                    },
                }

            keys = [{"t": 0.0, "x": 0.1, "y": 0.5}, {"t": 1.0, "x": 0.9, "y": 0.5},
                    {"t": 2.0, "x": 0.9, "y": 0.5}]
            cfg = config(keys)
            cfg_path = work / "cfg.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            output = work / "out.mp4"
            run_render(source, output, 0.0, 2.0, cfg, cfg_path, "cpu")

            capture = cv2.VideoCapture(str(output))
            centroids = []
            index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if index in (0, 19):
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    ys, xs = (gray > 220).nonzero()
                    centroids.append(float(xs.mean()) if len(xs) else -1.0)
                index += 1
            capture.release()

            self.assertEqual(len(centroids), 2)
            start_x, end_x = centroids
            # 0.1 * 180 = 18px at the start, 0.9 * 180 = 162px at the end (centred).
            self.assertAlmostEqual(start_x, 18.0, delta=8.0)
            self.assertAlmostEqual(end_x, 162.0, delta=8.0)


if __name__ == "__main__":
    unittest.main()
