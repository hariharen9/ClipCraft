from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fasttrack_script", ROOT / "fasttrack.py")
fasttrack_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fasttrack_script)

parse_time = fasttrack_script.parse_time
build_parser = fasttrack_script.build_parser
default_output = fasttrack_script.default_output


class TestCli(unittest.TestCase):
    """Test CLI argument parsing and time conversion."""

    def test_parse_time_seconds(self):
        self.assertAlmostEqual(parse_time("0"), 0.0)
        self.assertAlmostEqual(parse_time("12.5"), 12.5)
        self.assertAlmostEqual(parse_time("120"), 120.0)

    def test_parse_time_mmss(self):
        self.assertAlmostEqual(parse_time("1:30"), 90.0)
        self.assertAlmostEqual(parse_time("02:15.5"), 135.5)

    def test_parse_time_hhmmss(self):
        self.assertAlmostEqual(parse_time("01:00:00"), 3600.0)
        self.assertAlmostEqual(parse_time("01:02:03.500"), 3723.5)

    def test_parse_time_invalid(self):
        for invalid in ("", "   ", "abc", "-5", "1:2:3:4"):
            with self.subTest(val=invalid):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parse_time(invalid)

    def test_build_parser_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["video.mp4"])
        self.assertEqual(args.video, "video.mp4")
        self.assertIsNone(args.in_time)
        self.assertIsNone(args.out_time)
        self.assertEqual(args.encoder, "auto")
        self.assertFalse(args.gui)
        self.assertFalse(args.batch)

    def test_build_parser_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "clip.mp4",
            "-g", "valorant",
            "--in", "10",
            "--out", "1:15",
            "--encoder", "nvenc",
            "-o", "out.mp4",
        ])
        self.assertEqual(args.video, "clip.mp4")
        self.assertEqual(args.game, "valorant")
        self.assertAlmostEqual(args.in_time, 10.0)
        self.assertAlmostEqual(args.out_time, 75.0)
        self.assertEqual(args.encoder, "nvenc")
        self.assertEqual(args.output, "out.mp4")

    def test_default_output(self):
        p = Path("C:/Recordings/gameplay.mp4")
        out = default_output(p, "valorant")
        self.assertEqual(out.name, "gameplay_valorant_short.mp4")
        self.assertEqual(out.parent.name, "exports")


if __name__ == "__main__":
    unittest.main()
