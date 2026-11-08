"""Cut-list timeline math shared by the renderer, the preview and the split editor.

A clip is described by an IN point, an OUT point and a list of *cut* regions
(absolute source timestamps). Everything the user wants to keep is the set of
"kept spans": ``[IN, OUT]`` with every cut region subtracted.

Two time domains are used throughout ClipCraft:

* **source time** — seconds measured from the start of the video file. The
  renderer, ``in_spin``/``out_spin`` and the cut list all use source time.
* **timeline time** — seconds measured along the *edited* result, i.e. the kept
  footage with the cut regions closed up. The transport scrubber runs on this
  domain so the dead regions never appear while dragging.

All functions are pure and dependency-free so they can be unit tested without
Qt, FFmpeg or a real video file.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import TypeAlias

Cut: TypeAlias = tuple[float, float]

# Regions shorter than this are treated as no-ops. Roughly one frame at 60 fps;
# trimming to a sub-frame span makes FFmpeg emit zero frames for that segment.
MIN_CUT: float = 0.002
EPSILON: float = 1e-9


def _as_cut(item: object) -> Cut | None:
    """Coerce one ``(start, end)`` pair, rejecting anything malformed."""
    try:
        start, end = item  # type: ignore[misc]
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(start) and math.isfinite(end)):
        return None
    if end < start:
        start, end = end, start
    return start, end


def normalize_cuts(
    cuts: Iterable[Sequence[float]] | None,
    duration: float | None = None,
) -> list[Cut]:
    """Clamp, sort, merge and de-duplicate cut regions.

    Overlapping or touching regions are merged so the renderer never has to
    express the same removal twice, and zero-length regions are dropped.
    """
    cleaned: list[Cut] = []
    for item in cuts or []:
        cut = _as_cut(item)
        if cut is None:
            continue
        start, end = cut
        start = max(0.0, start)
        if duration is not None and math.isfinite(float(duration)):
            end = min(max(0.0, float(duration)), end)
        if end - start <= MIN_CUT:
            continue
        cleaned.append((start, end))

    cleaned.sort()
    merged: list[Cut] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1] + EPSILON:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def kept_spans(
    start: float,
    end: float,
    cuts: Iterable[Sequence[float]] | None = None,
) -> list[Cut]:
    """Return the footage inside ``[start, end]`` that is *not* cut away.

    Spans are absolute source times, sorted, and non-overlapping.
    """
    start, end = float(start), float(end)
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        return []

    spans: list[Cut] = []
    cursor = start
    for cut_start, cut_end in normalize_cuts(cuts):
        if cut_end <= cursor:
            continue
        if cut_start >= end:
            break
        if cut_start > cursor:
            spans.append((cursor, min(cut_start, end)))
        cursor = max(cursor, cut_end)
        if cursor >= end:
            break
    if cursor < end:
        spans.append((cursor, end))

    return [(a, b) for a, b in spans if b - a > EPSILON]


def timeline_duration(
    start: float,
    end: float,
    cuts: Iterable[Sequence[float]] | None = None,
) -> float:
    """Length of the edited result: ``(end - start)`` minus what was cut."""
    return sum(b - a for a, b in kept_spans(start, end, cuts))


def total_cut_time(cuts: Iterable[Sequence[float]] | None) -> float:
    """Total duration removed by the cut list."""
    return sum(b - a for a, b in normalize_cuts(cuts))


def cut_containing(time_value: float, cuts: Iterable[Sequence[float]] | None) -> Cut | None:
    """The cut region containing ``time_value``, or ``None`` if it is kept."""
    value = float(time_value)
    for cut_start, cut_end in normalize_cuts(cuts):
        if cut_start - EPSILON <= value < cut_end - EPSILON:
            return cut_start, cut_end
        if value < cut_start:
            break
    return None


def next_kept_time(time_value: float, cuts: Iterable[Sequence[float]] | None) -> float:
    """If ``time_value`` sits inside a cut, skip forward to where footage resumes."""
    cut = cut_containing(time_value, cuts)
    return cut[1] if cut else float(time_value)


def previous_kept_time(time_value: float, cuts: Iterable[Sequence[float]] | None) -> float:
    """If ``time_value`` sits inside a cut, skip back to where footage stops."""
    cut = cut_containing(time_value, cuts)
    return cut[0] if cut else float(time_value)


def source_to_timeline(
    time_value: float,
    start: float,
    end: float,
    cuts: Iterable[Sequence[float]] | None = None,
) -> float:
    """Map an absolute source timestamp onto the edited timeline."""
    value = float(time_value)
    spans = kept_spans(start, end, cuts)
    if not spans:
        return 0.0
    if value <= spans[0][0]:
        return 0.0
    offset = 0.0
    for span_start, span_end in spans:
        if value < span_start:
            # Inside a removed gap: collapse onto the point where the gap starts.
            return offset
        if value <= span_end:
            return offset + (value - span_start)
        offset += span_end - span_start
    return offset


def timeline_to_source(
    offset: float,
    start: float,
    end: float,
    cuts: Iterable[Sequence[float]] | None = None,
) -> float:
    """Map an offset on the edited timeline back to an absolute source timestamp."""
    remaining = max(0.0, float(offset))
    spans = kept_spans(start, end, cuts)
    if not spans:
        return float(start)
    for span_start, span_end in spans:
        length = span_end - span_start
        if remaining <= length + EPSILON:
            return min(span_end, span_start + remaining)
        remaining -= length
    return spans[-1][1]


def step_time(
    time_value: float,
    delta: float,
    start: float,
    end: float,
    cuts: Iterable[Sequence[float]] | None = None,
) -> float:
    """Move ``delta`` seconds through kept footage only, hopping over cut regions.

    This is what frame stepping and shuttle playback use: the playhead never
    rests inside a removed region.
    """
    spans = kept_spans(start, end, cuts)
    if not spans or delta == 0:
        return max(float(start), min(float(end), float(time_value)))

    if delta > 0:
        cursor = max(float(time_value), start)
        remaining = float(delta)
        for span_start, span_end in spans:
            if cursor < span_start:
                cursor = span_start  # hop the gap
            if cursor > span_end:
                continue
            room = span_end - cursor
            if remaining <= room:
                return cursor + remaining
            remaining -= room
            cursor = span_end
            # A step that lands exactly on the boundary leaves ~1e-16 of float
            # dust behind; stop here instead of hopping the next gap.
            if remaining <= EPSILON:
                return cursor
        return spans[-1][1]

    cursor = min(float(time_value), end)
    remaining = -float(delta)
    for span_start, span_end in reversed(spans):
        if cursor > span_end:
            cursor = span_end  # hop the gap backwards
        if cursor < span_start:
            continue
        room = cursor - span_start
        if remaining <= room:
            return cursor - remaining
        remaining -= room
        cursor = span_start
        if remaining <= EPSILON:
            return cursor
    return spans[0][0]
