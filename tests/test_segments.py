from __future__ import annotations

import unittest

from clipcraft.segments import (
    MIN_CUT,
    cut_containing,
    kept_spans,
    next_kept_time,
    normalize_cuts,
    previous_kept_time,
    source_to_timeline,
    step_time,
    timeline_duration,
    timeline_to_source,
    total_cut_time,
)


class TestNormalizeCuts(unittest.TestCase):
    def test_sorts_and_merges_overlaps(self):
        self.assertEqual(
            normalize_cuts([(5, 7), (1, 3), (2.5, 4)]),
            [(1.0, 4.0), (5.0, 7.0)],
        )

    def test_merges_touching_regions(self):
        self.assertEqual(normalize_cuts([(1, 2), (2, 3)]), [(1.0, 3.0)])

    def test_swaps_reversed_and_clamps_to_duration(self):
        self.assertEqual(normalize_cuts([(9, 4)], duration=6), [(4.0, 6.0)])

    def test_drops_zero_length_and_garbage(self):
        self.assertEqual(normalize_cuts([(3, 3), (2, 2 + MIN_CUT / 2), None, ("x", "y")]), [])

    def test_negative_start_clamped(self):
        self.assertEqual(normalize_cuts([(-5, 2)]), [(0.0, 2.0)])


class TestKeptSpans(unittest.TestCase):
    def test_no_cuts_is_single_span(self):
        self.assertEqual(kept_spans(0, 10), [(0.0, 10.0)])

    def test_middle_cut_splits_span(self):
        self.assertEqual(kept_spans(0, 10, [(3, 5)]), [(0.0, 3.0), (5.0, 10.0)])

    def test_cut_at_start_and_end(self):
        self.assertEqual(kept_spans(0, 10, [(0, 2), (8, 10)]), [(2.0, 8.0)])

    def test_cut_outside_range_is_ignored(self):
        self.assertEqual(kept_spans(2, 8, [(0, 1), (9, 10)]), [(2.0, 8.0)])

    def test_cut_covering_whole_range_leaves_nothing(self):
        self.assertEqual(kept_spans(2, 8, [(0, 10)]), [])

    def test_span_inside_cut_is_removed(self):
        # A cut that starts before the range but ends inside it.
        self.assertEqual(kept_spans(2, 8, [(0, 4)]), [(4.0, 8.0)])


class TestDurations(unittest.TestCase):
    def test_timeline_duration_subtracts_cuts(self):
        self.assertAlmostEqual(timeline_duration(0, 10, [(3, 5), (7, 8)]), 7.0)

    def test_total_cut_time_merges(self):
        self.assertAlmostEqual(total_cut_time([(0, 2), (1, 3)]), 3.0)


class TestTimelineMapping(unittest.TestCase):
    cuts = [(3.0, 5.0)]

    def test_source_to_timeline_before_cut(self):
        self.assertAlmostEqual(source_to_timeline(2.0, 0, 10, self.cuts), 2.0)

    def test_source_to_timeline_inside_cut_collapses(self):
        self.assertAlmostEqual(source_to_timeline(4.0, 0, 10, self.cuts), 3.0)

    def test_source_to_timeline_after_cut_is_shifted(self):
        self.assertAlmostEqual(source_to_timeline(6.0, 0, 10, self.cuts), 4.0)

    def test_timeline_to_source_roundtrip(self):
        # Values away from a cut boundary round-trip exactly.
        for source in (0.0, 1.25, 2.99, 5.01, 7.5, 10.0):
            offset = source_to_timeline(source, 0, 10, self.cuts)
            self.assertAlmostEqual(timeline_to_source(offset, 0, 10, self.cuts), source, places=6)

    def test_cut_boundary_collapses_to_one_offset(self):
        # Both edges of the removed region share timeline offset 3.0; the mapping
        # back resolves to the last kept frame before the cut.
        self.assertAlmostEqual(source_to_timeline(3.0, 0, 10, self.cuts), 3.0)
        self.assertAlmostEqual(source_to_timeline(5.0, 0, 10, self.cuts), 3.0)
        self.assertAlmostEqual(timeline_to_source(3.0, 0, 10, self.cuts), 3.0)

    def test_timeline_offset_past_end_clamps(self):
        self.assertAlmostEqual(timeline_to_source(999.0, 0, 10, self.cuts), 10.0)


class TestSkipHelpers(unittest.TestCase):
    cuts = [(3.0, 5.0)]

    def test_detects_cut_membership(self):
        self.assertEqual(cut_containing(4.0, self.cuts), (3.0, 5.0))
        self.assertIsNone(cut_containing(2.99, self.cuts))
        self.assertIsNone(cut_containing(5.0, self.cuts))

    def test_next_and_previous_kept(self):
        self.assertAlmostEqual(next_kept_time(4.0, self.cuts), 5.0)
        self.assertAlmostEqual(previous_kept_time(4.0, self.cuts), 3.0)
        self.assertAlmostEqual(next_kept_time(1.0, self.cuts), 1.0)


class TestStepTime(unittest.TestCase):
    def test_forward_step_inside_span(self):
        self.assertAlmostEqual(step_time(1.0, 0.5, 0, 10, [(3, 5)]), 1.5)

    def test_forward_step_hops_over_cut(self):
        # 2.8 + 0.4 would land at 3.2 inside the cut; it should continue past 5.0.
        self.assertAlmostEqual(step_time(2.8, 0.4, 0, 10, [(3, 5)]), 5.0 + (0.4 - 0.2))

    def test_backward_step_hops_over_cut(self):
        # 5.1 - 0.4 would land at 4.7 inside the cut; continue from 3.0 backwards.
        self.assertAlmostEqual(step_time(5.1, -0.4, 0, 10, [(3, 5)]), 3.0 - 0.3)

    def test_step_clamps_at_bounds(self):
        self.assertAlmostEqual(step_time(9.9, 5.0, 0, 10), 10.0)
        self.assertAlmostEqual(step_time(0.1, -5.0, 0, 10), 0.0)

    def test_step_into_multiple_cuts(self):
        cuts = [(1.0, 1.5), (2.0, 3.0)]
        # Walking 1.2s from 0: 0→1 (1.0s), hop to 1.5, 1.5→2.0 (0.5s)... exceeds,
        # so it should land at 1.0 + 0.2 = 1.2? No: 1.2 is inside cut (1.0,1.5),
        # so the walk hops to 1.5 and consumes the remaining 0.2 there.
        self.assertAlmostEqual(step_time(0.0, 1.2, 0, 10, cuts), 1.7)

    def test_zero_delta_is_identity(self):
        self.assertAlmostEqual(step_time(4.2, 0.0, 0, 10, [(3, 5)]), 4.2)

    def test_forward_step_landing_exactly_on_cut_start(self):
        # Regression: float dust made this hop the whole cut instead of stopping.
        self.assertAlmostEqual(step_time(1.9, 0.1, 0, 8, [(2, 4)]), 2.0, places=9)

    def test_backward_step_landing_exactly_on_cut_end(self):
        self.assertAlmostEqual(step_time(4.1, -0.1, 0, 8, [(2, 4)]), 4.0, places=9)

    def test_step_from_a_cut_boundary_hops_the_gap(self):
        self.assertAlmostEqual(step_time(2.0, 1 / 30, 0, 8, [(2, 4)]), 4.0 + 1 / 30, places=9)
        self.assertAlmostEqual(step_time(4.0, -1 / 30, 0, 8, [(2, 4)]), 2.0 - 1 / 30, places=9)


if __name__ == "__main__":
    unittest.main()
