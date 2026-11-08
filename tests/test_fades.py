from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from clipcraft.renderer import build_filter_complex, build_layer_fade_filter, find_ffmpeg

try:
    import cv2
except Exception:  # pragma: no cover - only on a broken install
    cv2 = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


def _config(*, background_extra: dict | None = None, layers_extra: dict | None = None) -> dict:
    background = {"kind": "background", "rect": [0, 0, 1, 1], "z": 0, "visible": True}
    background.update(background_extra or {})
    layers = {
        "background": background,
        "main": {"kind": "video", "rect": [0, 0.5, 1, 0.5], "crop": [0, 0, 1, 1],
                 "fit": "cover", "z": 10, "visible": True},
    }
    layers.update(layers_extra or {})
    return {
        "version": 1, "name": "fadetest",
        "canvas": {"width": 180, "height": 320, "fps": 10, "encoder": "cpu", "quality": 18,
                   "x264_preset": "ultrafast"},
        "background": {"blur": 1, "brightness": 0.0, "saturation": 1.0},
        "layers": layers,
    }


class TestLayerFadeFilter(unittest.TestCase):
    """Unit tests for the per-layer fade chain (no FFmpeg needed)."""

    def test_disabled_layer_has_no_fade(self):
        self.assertEqual(build_layer_fade_filter({}, 10.0), "")
        self.assertEqual(build_layer_fade_filter({"fade_enabled": False, "fade_in": 1}, 10.0), "")

    def test_defaults_are_half_a_second_each(self):
        chain = build_layer_fade_filter({"fade_enabled": True}, 10.0)
        self.assertEqual(
            chain,
            ",fade=t=in:st=0:d=0.5000:alpha=1,fade=t=out:st=9.5000:d=0.5000:alpha=1",
        )

    def test_background_uses_colour_fade_not_alpha(self):
        chain = build_layer_fade_filter({"fade_enabled": True}, 10.0, alpha=False)
        self.assertIn("fade=t=in:st=0:d=0.5000", chain)
        self.assertNotIn("alpha=1", chain)

    def test_fade_out_anchored_to_edited_duration(self):
        # A 4s trim with 1-2s cut exports 3s, so a 0.5s fade-out starts at 2.5s.
        chain = build_layer_fade_filter({"fade_enabled": True, "fade_out": 0.5}, 3.0)
        self.assertIn("fade=t=out:st=2.5000:d=0.5000:alpha=1", chain)

    def test_durations_are_clamped_to_the_clip(self):
        chain = build_layer_fade_filter(
            {"fade_enabled": True, "fade_in": 5.0, "fade_out": 5.0}, 0.4
        )
        self.assertIn("d=0.4000", chain)

    def test_zero_durations_produce_no_chain(self):
        self.assertEqual(
            build_layer_fade_filter({"fade_enabled": True, "fade_in": 0.0, "fade_out": 0.0}, 10.0),
            "",
        )

    def test_without_a_duration_only_fade_in_can_be_placed(self):
        chain = build_layer_fade_filter({"fade_enabled": True}, None)
        self.assertIn("fade=t=in", chain)
        self.assertNotIn("fade=t=out", chain)


class TestFadeGraph(unittest.TestCase):
    def test_video_layer_gains_rgba_and_fade(self):
        config = _config()
        config["layers"]["main"].update({"fade_enabled": True, "fade_in": 1.0, "fade_out": 1.0})
        graph, _ = build_filter_complex(config, Path("cfg.json"), {}, duration=4.0)
        chain = next(c for c in graph.split(";") if "[lay_main]" in c)
        self.assertIn("format=rgba", chain)
        self.assertIn("fade=t=in:st=0:d=1.0000:alpha=1", chain)
        self.assertIn("fade=t=out:st=3.0000:d=1.0000:alpha=1", chain)

    def test_background_fade_is_colour_only(self):
        config = _config(background_extra={"fade_enabled": True, "fade_in": 1.0, "fade_out": 1.0})
        graph, _ = build_filter_complex(config, Path("cfg.json"), {}, duration=4.0)
        base_chain = next(c for c in graph.split(";") if "[base0]" in c)
        self.assertIn("fade=t=in:st=0:d=1.0000", base_chain)
        self.assertNotIn("alpha=1", base_chain)
        self.assertNotIn("format=rgba", base_chain)

    def test_layers_without_fades_are_untouched(self):
        graph, _ = build_filter_complex(_config(), Path("cfg.json"), {}, duration=4.0)
        self.assertNotIn("fade=", graph)


@unittest.skipIf(cv2 is None or Image is None, "OpenCV/Pillow not available")
class TestFadeRender(unittest.TestCase):
    """Render fades and measure the actual frames."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = find_ffmpeg()
        except FileNotFoundError:
            raise unittest.SkipTest("FFmpeg is not available")

    def _source(self, work: Path) -> Path:
        source = work / "src.mkv"
        subprocess.run(
            [self.ffmpeg, "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=3",
             "-c:v", "ffv1", str(source)],
            check=True,
        )
        return source

    def _frames(self, path: Path) -> list:
        capture = cv2.VideoCapture(str(path))
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
        capture.release()
        return frames

    def test_background_fade_darkens_first_and_last_frames(self):
        from clipcraft.renderer import run_render

        with tempfile.TemporaryDirectory(prefix="cc_fade_") as tmp:
            work = Path(tmp)
            source = self._source(work)
            config = _config(background_extra={"fade_enabled": True, "fade_in": 1.0, "fade_out": 1.0})
            config_path = work / "cfg.json"
            config_path.write_text(json.dumps(config))
            output = work / "out.mp4"
            run_render(source, output, 0.0, 3.0, config, config_path, "cpu")

            frames = self._frames(output)
            self.assertEqual(len(frames), 30)
            # The main layer covers only the bottom half, so the top strip is background.
            top = [float(f[0:60, :, :].mean()) for f in frames]
            self.assertLess(top[0], 5.0)
            self.assertGreater(top[15], 50.0)
            self.assertLess(top[-1], 40.0)

    def test_image_layer_alpha_fade_reveals_background(self):
        from clipcraft.renderer import run_render

        with tempfile.TemporaryDirectory(prefix="cc_fade_") as tmp:
            work = Path(tmp)
            source = self._source(work)
            white = work / "white.png"
            Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(white)
            config = _config(layers_extra={
                "logo": {"kind": "image", "asset": str(white), "rect": [0.1, 0.1, 0.8, 0.8],
                         "fit": "fill", "opacity": 1.0, "z": 20, "visible": True,
                         "fade_enabled": True, "fade_in": 1.0, "fade_out": 1.0},
            })
            config_path = work / "cfg.json"
            config_path.write_text(json.dumps(config))
            output = work / "out.mp4"
            run_render(source, output, 0.0, 3.0, config, config_path, "cpu")

            frames = self._frames(output)
            centre = [int(f[f.shape[0] // 2, f.shape[1] // 2].mean()) for f in frames]
            # At the start the white overlay is transparent, so the frame is not white.
            self.assertLess(centre[0], 200)
            # Mid-clip the overlay is fully opaque.
            self.assertGreater(centre[15], 240)
            # It fades out again towards the end.
            self.assertLess(centre[-1], 200)


if __name__ == "__main__":
    unittest.main()
