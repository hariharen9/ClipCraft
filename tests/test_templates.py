from __future__ import annotations

import json
from pathlib import Path
import unittest

from clipcraft.config import available_templates, template_path, load_config, clone_config


class TestTemplates(unittest.TestCase):
    """Verify all shipping templates are valid JSON and conform to the schema."""

    def test_available_templates(self):
        templates = available_templates()
        self.assertGreaterEqual(len(templates), 1, "At least one template must be available")
        game_ids = [t[0] for t in templates]
        self.assertIn("valorant", game_ids)

    def test_templates_schema(self):
        root = Path(__file__).resolve().parent.parent
        tmpl_dir = root / "templates"
        self.assertTrue(tmpl_dir.is_dir(), "templates/ folder must exist")

        json_files = list(tmpl_dir.glob("*.json"))
        self.assertGreaterEqual(len(json_files), 1, "There should be template JSON files in templates/")

        for jf in json_files:
            with self.subTest(template=jf.name):
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self.assertIn("canvas", data, f"{jf.name} missing 'canvas'")
                self.assertIn("width", data["canvas"], f"{jf.name} missing 'canvas.width'")
                self.assertIn("height", data["canvas"], f"{jf.name} missing 'canvas.height'")
                self.assertGreater(data["canvas"]["width"], 0)
                self.assertGreater(data["canvas"]["height"], 0)

                self.assertIn("layers", data, f"{jf.name} missing 'layers'")
                self.assertIsInstance(data["layers"], dict)

                # Check each layer in the template
                for layer_name, layer in data["layers"].items():
                    self.assertIn("kind", layer, f"Layer '{layer_name}' in {jf.name} missing 'kind'")
                    self.assertIn(layer["kind"], ("video", "image", "text", "background"))
                    self.assertIn("rect", layer, f"Layer '{layer_name}' in {jf.name} missing 'rect'")
                    self.assertEqual(len(layer["rect"]), 4, f"Layer '{layer_name}' rect must have 4 items")

    def test_clone_config(self):
        cfg, _ = load_config(template_path("valorant"))
        cloned = clone_config(cfg)
        self.assertEqual(cfg, cloned)
        cloned["canvas"]["width"] = 9999
        self.assertNotEqual(cfg["canvas"]["width"], cloned["canvas"]["width"])

    def test_template_assets_resolve_or_generate(self):
        root = Path(__file__).resolve().parent.parent
        from clipcraft.assets import ensure_assets
        from clipcraft.config import resolve_asset
        tmpl_dir = root / "templates"
        for jf in tmpl_dir.glob("*.json"):
            with self.subTest(template=jf.name):
                cfg, p = load_config(jf)
                ensure_assets(cfg, p)
                for layer_name, layer in cfg.get("layers", {}).items():
                    if layer.get("kind") == "image":
                        asset_path = resolve_asset(p, layer.get("asset", ""))
                        self.assertTrue(asset_path.is_file(), f"Asset for '{layer_name}' in {jf.name} not found: {asset_path}")

    def test_layer_z_ordering_in_filter_complex(self):
        from clipcraft.renderer import build_filter_complex
        root = Path(__file__).resolve().parent.parent
        config = {
            "name": "CustomGame",
            "canvas": {"width": 1080, "height": 1920, "fps": 60},
            "background": {"blur": 10, "brightness": 0, "saturation": 1},
            "layers": {
                "background": {"kind": "background", "rect": [0, 0, 1, 1], "z": 0, "visible": True},
                "under_logo": {"kind": "text", "text": "Under", "rect": [0, 0, 0.5, 0.1], "z": 5, "visible": True},
                "main": {"kind": "video", "rect": [0, 0.2, 1, 0.6], "crop": [0, 0, 1, 1], "z": 10, "visible": True},
                "top_title": {"kind": "text", "text": "Top", "rect": [0, 0.8, 0.5, 0.1], "z": 20, "visible": True},
            }
        }
        graph, inputs = build_filter_complex(
            config, root / "templates" / "custom.json",
            {"duration": 10, "width": 1920, "height": 1080, "fps": 60}
        )
        under_idx = graph.find("[txt_under_logo]")
        main_idx = graph.find("[lay_main]")
        top_idx = graph.find("[txt_top_title]")
        self.assertNotEqual(under_idx, -1)
        self.assertNotEqual(main_idx, -1)
        self.assertNotEqual(top_idx, -1)
        self.assertLess(under_idx, main_idx, "Layer at z=5 should be processed before layer at z=10")
        self.assertLess(main_idx, top_idx, "Layer at z=10 should be processed before layer at z=20")

    def test_missing_main_layer_error_message(self):
        from clipcraft.renderer import build_filter_complex
        root = Path(__file__).resolve().parent.parent
        config = {
            "name": "Apex Legends",
            "canvas": {"width": 1080, "height": 1920, "fps": 60},
            "background": {"blur": 10, "brightness": 0, "saturation": 1},
            "layers": {
                "background": {"kind": "background", "rect": [0, 0, 1, 1], "z": 0, "visible": True},
            }
        }
        with self.assertRaises(ValueError) as ctx:
            build_filter_complex(
                config, root / "templates" / "apex.json",
                {"duration": 10, "width": 1920, "height": 1080, "fps": 60}
            )
        self.assertIn("Apex Legends", str(ctx.exception))
        self.assertNotIn("Valorant", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
