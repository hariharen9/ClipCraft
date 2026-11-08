from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from clipcraft.silence import (
    _shrink,
    detect_silence,
    parse_silencedetect,
    total_cut_time,
)

SAMPLE_LOG = """
[silencedetect @ 000001] silence_start: 1.5
[silencedetect @ 000001] silence_end: 3.25 | silence_duration: 1.75
[silencedetect @ 000001] silence_start: 7.0
[silencedetect @ 000001] silence_end: 7.4 | silence_duration: 0.4
"""


class TestParseSilencedetect(unittest.TestCase):
    def test_parses_pairs(self):
        self.assertEqual(parse_silencedetect(SAMPLE_LOG), [(1.5, 3.25), (7.0, 7.4)])

    def test_applies_the_seek_offset(self):
        self.assertEqual(parse_silencedetect(SAMPLE_LOG, start_offset=10.0), [(11.5, 13.25), (17.0, 17.4)])

    def test_unclosed_silence_is_closed_at_the_end(self):
        log = "[silencedetect @ 0] silence_start: 4.0\n"
        self.assertEqual(parse_silencedetect(log, total=6.0), [(4.0, 6.0)])

    def test_unclosed_silence_without_total_is_dropped(self):
        self.assertEqual(parse_silencedetect("[silencedetect @ 0] silence_start: 4.0\n"), [])

    def test_empty_log(self):
        self.assertEqual(parse_silencedetect(""), [])

    def test_falls_back_to_duration_when_end_only(self):
        log = "[silencedetect @ 0] silence_end: 5.0 | silence_duration: 0.5\n"
        self.assertEqual(parse_silencedetect(log), [(4.5, 5.0)])


class TestShrink(unittest.TestCase):
    def test_padding_pulls_regions_inward(self):
        self.assertEqual(_shrink([(2.0, 3.0)], 0.1), [(2.1, 2.9)])

    def test_regions_that_vanish_are_dropped(self):
        self.assertEqual(_shrink([(2.0, 2.05)], 0.1), [])

    def test_zero_padding_is_a_no_op(self):
        self.assertEqual(_shrink([(2.0, 3.0)], 0.0), [(2.0, 3.0)])


class TestTotalCutTime(unittest.TestCase):
    def test_sums_and_merges(self):
        self.assertAlmostEqual(total_cut_time([(1, 2), (1.5, 3)]), 2.0)


class TestDetectSilenceIntegration(unittest.TestCase):
    """Runs FFmpeg's silencedetect against a synthetic tone/silence pattern."""

    @classmethod
    def setUpClass(cls):
        from clipcraft.renderer import find_ffmpeg

        try:
            cls.ffmpeg = find_ffmpeg()
        except FileNotFoundError:
            raise unittest.SkipTest("FFmpeg is not available")

    def _source(self, work: Path) -> Path:
        # 6s of 440 Hz tone with silent gaps at 2-3s and 4-5s.
        source = work / "audio.wav"
        expression = "if(between(t,2,3)+between(t,4,5),0,sin(2*PI*440*t))"
        subprocess.run(
            [self.ffmpeg, "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", f"aevalsrc=exprs='{expression}':s=48000:d=6",
             "-c:a", "pcm_s16le", str(source)],
            check=True,
        )
        return source

    def test_finds_the_expected_gaps(self):
        with tempfile.TemporaryDirectory(prefix="cc_silence_") as tmp:
            source = self._source(Path(tmp))
            regions = detect_silence(source, 0.0, 6.0, min_silence=0.3, padding=0.08)
            self.assertEqual(len(regions), 2)
            self.assertAlmostEqual(regions[0][0], 2.0, delta=0.2)
            self.assertAlmostEqual(regions[0][1], 3.0, delta=0.2)
            self.assertAlmostEqual(regions[1][0], 4.0, delta=0.2)
            self.assertAlmostEqual(regions[1][1], 5.0, delta=0.2)

    def test_range_is_respected(self):
        with tempfile.TemporaryDirectory(prefix="cc_silence_") as tmp:
            source = self._source(Path(tmp))
            regions = detect_silence(source, 0.0, 3.5, min_silence=0.3, padding=0.0)
            self.assertEqual(len(regions), 1)
            self.assertAlmostEqual(regions[0][0], 2.0, delta=0.2)

    def test_empty_range_returns_nothing(self):
        self.assertEqual(detect_silence("whatever.mp4", 5.0, 5.0), [])


if __name__ == "__main__":
    unittest.main()
