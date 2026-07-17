"""Interval utilities: overlap testing, merging, and non-overlap selection.

Intervals are ``(start, end)`` pairs of comparable numbers with the convention
that they are half-open, ``[start, end)`` — so two intervals that merely touch
at an endpoint (``[0, 5)`` and ``[5, 9)``) are considered adjacent, not
overlapping. This module offers:

* :func:`overlaps` — do two intervals share any interior point?
* :func:`merge_intervals` — collapse a set of intervals into the minimal set of
  disjoint intervals covering the same points.
* :func:`select_non_overlapping` — greedily pick the largest subset of mutually
  non-overlapping intervals (activity selection), returned in start order.

Degenerate intervals where ``start > end`` are rejected; empty intervals where
``start == end`` are permitted but never overlap anything.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, TypeVar

__all__ = ["overlaps", "merge_intervals", "select_non_overlapping", "IntervalError"]

T = TypeVar("T")
Interval = Tuple[T, T]


class IntervalError(ValueError):
    """Raised when an interval is malformed (e.g. start after end)."""


def _validate(interval: Interval) -> Interval:
    if not isinstance(interval, (tuple, list)) or len(interval) != 2:
        raise IntervalError(f"interval must be a 2-tuple, got {interval!r}")
    start, end = interval[0], interval[1]
    try:
        inverted = end < start
    except TypeError as exc:
        raise IntervalError("interval endpoints must be comparable") from exc
    if inverted:
        raise IntervalError(f"interval start {start!r} is after end {end!r}")
    return (start, end)


def _is_empty(interval: Interval) -> bool:
    return not (interval[0] < interval[1])


def overlaps(a: Interval, b: Interval) -> bool:
    """Return ``True`` if half-open intervals ``a`` and ``b`` share a point.

    Empty intervals (``start == end``) contain no points and never overlap.
    Intervals that only touch at an endpoint do not overlap.
    """
    a = _validate(a)
    b = _validate(b)
    if _is_empty(a) or _is_empty(b):
        return False
    return a[0] < b[1] and b[0] < a[1]


def overlap_amount(a: Interval, b: Interval):
    """Return the size of the overlap between ``a`` and ``b`` (0 if disjoint)."""
    a = _validate(a)
    b = _validate(b)
    lo = a[0] if a[0] > b[0] else b[0]
    hi = a[1] if a[1] < b[1] else b[1]
    if hi <= lo:
        return lo - lo  # zero of the appropriate numeric type
    return hi - lo


def merge_intervals(intervals: Sequence[Interval]) -> List[Interval]:
    """Collapse overlapping/adjacent intervals into a minimal disjoint set.

    Empty intervals are discarded. The result is sorted by start. Two intervals
    are combined when they overlap *or* touch (``prev_end >= next_start``), so
    ``[0, 5)`` and ``[5, 9)`` fuse into ``[0, 9)``.
    """
    cleaned = [_validate(iv) for iv in intervals]
    cleaned = [iv for iv in cleaned if not _is_empty(iv)]
    if not cleaned:
        return []

    ordered = sorted(cleaned, key=lambda iv: (iv[0], iv[1]))
    merged: List[Interval] = [ordered[0]]

    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))

    return merged


def total_covered(intervals: Sequence[Interval]):
    """Return the total measure covered by the union of ``intervals``."""
    merged = merge_intervals(intervals)
    if not merged:
        return 0
    total = merged[0][1] - merged[0][0]
    for start, end in merged[1:]:
        total = total + (end - start)
    return total


def select_non_overlapping(intervals: Sequence[Interval]) -> List[Interval]:
    """Return the largest subset of mutually non-overlapping intervals.

    This is classic activity selection: sort by end, then walk left to right
    accepting any interval whose start is not before the last accepted end.
    Empty intervals are skipped. Ties on end are broken by earlier start so the
    selection is deterministic. The returned list is ordered by start.
    """
    candidates = [_validate(iv) for iv in intervals]
    candidates = [iv for iv in candidates if not _is_empty(iv)]
    if not candidates:
        return []

    by_finish = sorted(candidates, key=lambda iv: (iv[1], iv[0]))

    chosen: List[Interval] = []
    current_end = None
    for start, end in by_finish:
        if current_end is None or start >= current_end:
            chosen.append((start, end))
            current_end = end

    chosen.sort(key=lambda iv: (iv[0], iv[1]))
    return chosen


def find_conflicts(intervals: Sequence[Interval]) -> List[Tuple[int, int]]:
    """Return index pairs ``(i, j)`` with ``i < j`` whose intervals overlap.

    Indices refer to positions in the original ``intervals`` sequence. Uses a
    sweep over start-sorted endpoints to avoid comparing every pair.
    """
    validated = [_validate(iv) for iv in intervals]
    order = sorted(range(len(validated)), key=lambda k: (validated[k][0], validated[k][1]))

    conflicts: List[Tuple[int, int]] = []
    active: List[int] = []
    for idx in order:
        start, _ = validated[idx]
        still_active: List[int] = []
        for other in active:
            if validated[other][1] > start:
                still_active.append(other)
        active = still_active
        for other in active:
            if overlaps(validated[other], validated[idx]):
                lo, hi = (other, idx) if other < idx else (idx, other)
                conflicts.append((lo, hi))
        active.append(idx)

    conflicts.sort()
    return conflicts


if __name__ == "__main__":
    assert overlaps((0, 5), (3, 8)) is True
    assert overlaps((0, 5), (5, 9)) is False  # touching, half-open
    assert overlaps((0, 5), (5, 5)) is False  # empty

    m = merge_intervals([(1, 4), (2, 5), (7, 9), (9, 12), (20, 20)])
    print("merged:", m)
    assert m == [(1, 5), (7, 12)], m

    print("covered:", total_covered([(1, 4), (2, 5), (7, 9)]))
    assert total_covered([(1, 4), (2, 5), (7, 9)]) == 6

    activities = [(1, 3), (2, 5), (4, 7), (1, 8), (5, 9), (8, 10)]
    picked = select_non_overlapping(activities)
    print("selected:", picked)
    assert picked == [(1, 3), (4, 7), (8, 10)], picked
    for i in range(len(picked) - 1):
        assert not overlaps(picked[i], picked[i + 1])

    print("conflicts:", find_conflicts([(0, 4), (2, 6), (5, 7)]))

    try:
        merge_intervals([(5, 1)])
    except IntervalError as err:
        print("rejected bad interval:", err)

    print("interval_scheduler smoke ok")
