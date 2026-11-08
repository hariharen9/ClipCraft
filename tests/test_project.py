from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from clipcraft.project import (
    PROJECT_SUFFIX,
    PROJECT_VERSION,
    build_project,
    load_project,
    normalize_project,
    project_path_for,
    push_recent_project,
    save_project,
)


class TestProjectPath(unittest.TestCase):
    def test_sidecar_sits_next_to_the_recording(self):
        path = project_path_for(Path("D:/Captures/clutch.mp4"))
        self.assertEqual(path.name, "clutch.clipcraft")
        self.assertEqual(path.suffix, PROJECT_SUFFIX)
        self.assertEqual(path.parent, Path("D:/Captures"))


class TestProjectRoundtrip(unittest.TestCase):
    def test_build_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "clip.clipcraft"
            project = build_project(
                "D:/Captures/clip.mp4", "valorant",
                in_time=2.5, out_time=42.0,
                cuts=[(10.0, 12.0), (11.0, 13.0)],  # overlapping: must merge
                audio={"bgm_path": "song.mp3", "bgm_volume": 0.4},
                captions={"enabled": True, "cues": []},
                playhead=5.0,
            )
            save_project(target, project)

            self.assertTrue(target.is_file())
            self.assertFalse(target.with_suffix(target.suffix + ".tmp").exists())

            loaded = load_project(target)
            self.assertEqual(loaded["version"], PROJECT_VERSION)
            self.assertEqual(Path(loaded["video"]).name, "clip.mp4")
            self.assertEqual(loaded["template"], "valorant")
            self.assertAlmostEqual(loaded["in"], 2.5)
            self.assertAlmostEqual(loaded["out"], 42.0)
            self.assertEqual(loaded["cuts"], [(10.0, 13.0)])
            self.assertEqual(loaded["audio"]["bgm_volume"], 0.4)
            self.assertTrue(loaded["captions"]["enabled"])
            self.assertAlmostEqual(loaded["playhead"], 5.0)
            self.assertTrue(loaded["saved_at"])

    def test_swapped_trim_is_repaired(self):
        project = normalize_project({"version": 1, "video": "a.mp4", "in": 30, "out": 10})
        self.assertAlmostEqual(project["in"], 10.0)
        self.assertAlmostEqual(project["out"], 30.0)

    def test_negative_values_are_clamped(self):
        project = normalize_project(
            {"version": 1, "video": "a.mp4", "in": -5, "out": 10, "playhead": -3,
             "cuts": [(-4, 2)]}
        )
        self.assertEqual(project["in"], 0.0)
        self.assertEqual(project["playhead"], 0.0)
        self.assertEqual(project["cuts"], [(0.0, 2.0)])

    def test_missing_video_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_project({"version": 1, "in": 0, "out": 5})

    def test_non_object_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_project(["not", "a", "project"])

    def test_newer_project_version_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            normalize_project({"version": PROJECT_VERSION + 1, "video": "a.mp4"})
        self.assertIn("newer", str(ctx.exception))

    def test_corrupt_json_raises_for_the_caller_to_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.clipcraft"
            broken.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_project(broken)

    def test_optional_sections_default_safely(self):
        project = normalize_project({"version": 1, "video": "a.mp4", "in": 0, "out": 5})
        self.assertEqual(project["audio"], {})
        self.assertIsNone(project["captions"])
        self.assertEqual(project["cuts"], [])


class TestRecentProjects(unittest.TestCase):
    def test_most_recent_first_and_deduplicated(self):
        first = push_recent_project([], "D:/a.clipcraft")
        second = push_recent_project(first, "D:/b.clipcraft")
        again = push_recent_project(second, "D:/a.clipcraft")
        self.assertEqual([Path(p).name for p in again], ["a.clipcraft", "b.clipcraft"])

    def test_list_is_capped(self):
        recent: list[str] = []
        for index in range(20):
            recent = push_recent_project(recent, f"D:/p{index}.clipcraft")
        self.assertEqual(len(recent), 10)
        self.assertTrue(recent[0].endswith("p19.clipcraft"))


if __name__ == "__main__":
    unittest.main()
