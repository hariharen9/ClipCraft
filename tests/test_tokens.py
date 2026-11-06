from __future__ import annotations

import unittest
from pathlib import Path
from datetime import datetime

from clipcraft.gui.constants import format_token_time


class TestTokens(unittest.TestCase):
    """Test output filename token formatting and substitution."""

    def test_format_token_time(self):
        self.assertEqual(format_token_time(0.0), "0s")
        self.assertEqual(format_token_time(9.4), "9s")
        self.assertEqual(format_token_time(59.4), "59s")
        self.assertEqual(format_token_time(60.0), "1m00s")
        self.assertEqual(format_token_time(75.2), "1m15s")
        self.assertEqual(format_token_time(125.0), "2m05s")
        self.assertEqual(format_token_time(-5.0), "0s")

    def test_token_substitution(self):
        video_stem = "MyRecording"
        game = "valorant"
        in_t = 10.0
        out_t = 75.0
        dur_t = out_t - in_t
        width = 1080
        height = 1920

        pattern = "{clip}_{game}_{in}-{out}"
        tokens = {
            "{clip}": video_stem,
            "{game}": game,
            "{in}": format_token_time(in_t),
            "{out}": format_token_time(out_t),
            "{dur}": format_token_time(dur_t),
            "{res}": f"{width}x{height}",
        }

        result = pattern
        for k, v in tokens.items():
            result = result.replace(k, v)

        self.assertEqual(result, "MyRecording_valorant_10s-1m15s")

    def test_custom_pattern_resolution(self):
        pattern = "{clip}_short"
        result = pattern.replace("{clip}", "ace_clutch")
        self.assertEqual(result, "ace_clutch_short")


if __name__ == "__main__":
    unittest.main()

