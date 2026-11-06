from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from fasttrack.config import get_state_file, load_state, save_state


class TestState(unittest.TestCase):
    """Test user UI state loading, saving, and path resolution."""

    def test_get_state_file_returns_path(self):
        path = get_state_file()
        self.assertIsInstance(path, Path)
        self.assertTrue(path.name.endswith(".json"))

    def test_save_and_load_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_state.json"
            sample_data = {
                "source_dir": "C:/Videos",
                "last_template": "valorant",
                "recent_files": ["C:/Videos/clip1.mp4", "C:/Videos/clip2.mp4"],
                "output_pattern": "{clip}_{game}_{in}-{out}",
            }
            save_state(sample_data, test_file)
            self.assertTrue(test_file.is_file())

            loaded = load_state(test_file)
            self.assertEqual(loaded, sample_data)

    def test_load_state_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            non_existent = Path(tmpdir) / "does_not_exist.json"
            loaded = load_state(non_existent)
            self.assertEqual(loaded, {})

    def test_load_state_corrupted_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            corrupted = Path(tmpdir) / "corrupted.json"
            corrupted.write_text("{invalid_json: true,", encoding="utf-8")
            loaded = load_state(corrupted)
            self.assertEqual(loaded, {})


if __name__ == "__main__":
    unittest.main()

