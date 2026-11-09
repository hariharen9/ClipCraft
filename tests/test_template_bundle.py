from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from clipcraft.template_bundle import bundle_template, slugify


def _config(assets: dict[str, str]) -> dict:
    layers = {
        "background": {"kind": "background", "rect": [0, 0, 1, 1], "z": 0, "visible": True},
        "main": {"kind": "video", "rect": [0, 0.5, 1, 0.5], "crop": [0, 0, 1, 1],
                 "fit": "cover", "z": 10, "visible": True},
    }
    for name, asset in assets.items():
        layers[name] = {"kind": "image", "asset": asset, "rect": [0, 0, 1, 1],
                        "fit": "fill", "opacity": 1.0, "z": 20, "visible": True}
    return {
        "version": 1, "name": "My Layout",
        "canvas": {"width": 1080, "height": 1920, "fps": 60, "encoder": "auto",
                   "quality": 14, "x264_preset": "medium"},
        "background": {"blur": 20, "brightness": -0.05, "saturation": 1.0},
        "layers": layers,
    }


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("My Cool Layout!"), "my_cool_layout")

    def test_empty_falls_back(self):
        self.assertEqual(slugify("   ###"), "template")


class TestBundleTemplate(unittest.TestCase):
    def test_copies_images_and_rewrites_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "originals"
            source_dir.mkdir()
            logo = source_dir / "Logo Image.png"
            Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(logo)

            templates_dir = root / "templates"
            templates_dir.mkdir()
            config = _config({"logo": str(logo), "missing": str(source_dir / "gone.png")})
            config_path = source_dir / "my_layout.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = bundle_template(config, config_path, "My Layout", templates_dir)

            self.assertEqual(result.template_id, "my_layout")
            self.assertTrue(result.path.is_file())
            self.assertEqual(len(result.copied), 1)
            self.assertTrue(any("gone.png" in item for item in result.missing))

            copied = templates_dir / "assets" / "my_layout" / "Logo_Image.png"
            self.assertTrue(copied.is_file())

            saved = json.loads(result.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["name"], "My Layout")
            self.assertEqual(saved["layers"]["logo"]["asset"], "assets/my_layout/Logo_Image.png")
            # The missing layer keeps its original path so the user can see what broke.
            self.assertEqual(saved["layers"]["missing"]["asset"], str(source_dir / "gone.png"))

    def test_second_save_gets_a_new_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates_dir = root / "templates"
            templates_dir.mkdir()
            config = _config({})
            config_path = root / "cfg.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            first = bundle_template(config, config_path, "Same Name", templates_dir)
            second = bundle_template(config, config_path, "Same Name", templates_dir)
            self.assertEqual(first.template_id, "same_name")
            self.assertEqual(second.template_id, "same_name_2")
            self.assertTrue(second.path.is_file())

    def test_shared_image_is_copied_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = root / "shared.png"
            Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(logo)
            templates_dir = root / "templates"
            templates_dir.mkdir()

            config = _config({"one": str(logo), "two": str(logo)})
            config_path = root / "cfg.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = bundle_template(config, config_path, "Shared", templates_dir)
            self.assertEqual(result.copied, ["shared.png"])
            saved = json.loads(result.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["layers"]["one"]["asset"], saved["layers"]["two"]["asset"])

    def test_relative_source_assets_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(root / "assets" / "icon.png")
            templates_dir = root / "templates"
            templates_dir.mkdir()

            config = _config({"icon": "assets/icon.png"})
            config_path = root / "cfg.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = bundle_template(config, config_path, "Relative", templates_dir)
            self.assertEqual(result.copied, ["icon.png"])
            self.assertTrue((templates_dir / "assets" / "relative" / "icon.png").is_file())

    def test_explicit_target_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates_dir = root / "templates"
            templates_dir.mkdir()
            config = _config({})
            config_path = root / "cfg.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = bundle_template(config, config_path, "Valorant Pro", templates_dir, target_id="valorant")
            self.assertEqual(result.template_id, "valorant")
            self.assertEqual(result.path.name, "valorant.json")
            self.assertTrue(result.path.is_file())

    def test_fallback_to_target_root_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates_dir = root / "templates"
            templates_dir.mkdir()
            (templates_dir / "assets").mkdir()
            Image.new("RGBA", (8, 8), (255, 255, 0, 255)).save(templates_dir / "assets" / "shared_logo.png")

            # Config is in an external folder that does not contain assets/shared_logo.png
            ext_dir = root / "downloads"
            ext_dir.mkdir()
            config = _config({"logo": "assets/shared_logo.png"})
            config_path = ext_dir / "downloaded.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            result = bundle_template(config, config_path, "Imported", templates_dir)
            self.assertEqual(result.copied, ["shared_logo.png"])
            self.assertTrue((templates_dir / "assets" / "imported" / "shared_logo.png").is_file())


if __name__ == "__main__":
    unittest.main()
