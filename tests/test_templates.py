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


if __name__ == "__main__":
    unittest.main()
