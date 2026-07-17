"""Sliding-window statistics over timestamped numeric samples.

``RollingStats`` accumulates ``(timestamp, value)`` observations and answers
aggregate queries — count, mean, min, max, and arbitrary percentiles — over
only the samples whose timestamps fall within the trailing ``window_seconds``
of the most recent observation. Old samples are evicted lazily: eviction runs
when data is added and again at query time, so the window never has to be
swept eagerly on a timer.

Timestamps are treated as monotonic floats (seconds). Out-of-order arrivals
within the current window are accepted and inserted in the correct position;
arrivals older than the window are dropped immediately.
"""

from __future__ import annotations

import bisect
from typing import Deque, List, Optional, Tuple
from collections import deque

__all__ = ["RollingStats", "EmptyWindowError"]

Sample = Tuple[float, float]


class EmptyWindowError(ValueError):
    """Raised when an aggregate is requested but the window holds no samples."""


class RollingStats:
    """A trailing-window accumulator for timestamped scalar samples.

    Parameters
    ----------
    window_seconds:
        Width of the trailing window. A sample at time ``t`` is retained while
        the newest observed timestamp ``now`` satisfies ``now - t <= window``.
    max_samples:
        Optional hard cap on retained samples; when exceeded the oldest are
        dropped even if still inside the time window. ``None`` means unbounded.
    """

    def __init__(self, window_seconds: float, max_samples: Optional[int] = None) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_samples is not None and max_samples <= 0:
            raise ValueError("max_samples must be positive when set")
        self.window_seconds = float(window_seconds)
        self.max_samples = max_samples
        self._samples: Deque[Sample] = deque()
        self._latest_ts: Optional[float] = None
        self._sum: float = 0.0

    # -- ingestion -------------------------------------------------------

    def add(self, ts: float, value: float) -> bool:
        """Record ``value`` observed at time ``ts``.

        Returns ``True`` if the sample was retained, ``False`` if it was too
        old to fall within the current window and therefore discarded.
        """
        ts = float(ts)
        value = float(value)

        if self._latest_ts is not None and ts < self._latest_ts:
            horizon = self._latest_ts - self.window_seconds
            if ts <= horizon:
                return False
            self._insert_ordered(ts, value)
        else:
            self._samples.append((ts, value))
            self._sum += value
            self._latest_ts = ts

        self._evict()
        return True

    def _insert_ordered(self, ts: float, value: float) -> None:
        keys = [s[0] for s in self._samples]
        idx = bisect.bisect_right(keys, ts)
        self._samples.insert(idx, (ts, value))
        self._sum += value

    def extend(self, samples: List[Sample]) -> int:
        """Add many samples; return how many were retained."""
        kept = 0
        for ts, value in samples:
            if self.add(ts, value):
                kept += 1
        return kept

    # -- eviction --------------------------------------------------------

    def _evict(self) -> None:
        if self._latest_ts is None:
            return
        horizon = self._latest_ts - self.window_seconds
        while self._samples and self._samples[0][0] <= horizon:
            _, dropped = self._samples.popleft()
            self._sum -= dropped
        if self.max_samples is not None:
            while len(self._samples) > self.max_samples:
                _, dropped = self._samples.popleft()
                self._sum -= dropped

    def _live(self) -> List[float]:
        self._evict()
        return [value for _, value in self._samples]

    # -- aggregates ------------------------------------------------------

    def count(self) -> int:
        """Number of samples currently inside the window."""
        self._evict()
        return len(self._samples)

    def is_empty(self) -> bool:
        return self.count() == 0

    def sum(self) -> float:
        self._evict()
        return self._sum

    def mean(self) -> float:
        self._evict()
        n = len(self._samples)
        if n == 0:
            raise EmptyWindowError("cannot take mean of an empty window")
        return self._sum / n

    def min(self) -> float:
        values = self._live()
        if not values:
            raise EmptyWindowError("cannot take min of an empty window")
        return min(values)

    def max(self) -> float:
        values = self._live()
        if not values:
            raise EmptyWindowError("cannot take max of an empty window")
        return max(values)

    def percentile(self, p: float) -> float:
        """Return the ``p``-th percentile (0..100) using linear interpolation.

        ``p=0`` is the minimum, ``p=100`` the maximum, ``p=50`` the median.
        Interpolation follows the "linear between closest ranks" convention.
        """
        if not 0.0 <= p <= 100.0:
            raise ValueError("percentile p must be in [0, 100]")
        values = sorted(self._live())
        n = len(values)
        if n == 0:
            raise EmptyWindowError("cannot take percentile of an empty window")
        if n == 1:
            return values[0]

        rank = (p / 100.0) * (n - 1)
        low = int(rank)
        frac = rank - low
        if low + 1 >= n:
            return values[-1]
        return values[low] + frac * (values[low + 1] - values[low])

    def median(self) -> float:
        return self.percentile(50.0)

    def range_span(self) -> float:
        """Return ``max - min`` over the live window."""
        values = self._live()
        if not values:
            raise EmptyWindowError("cannot compute range of an empty window")
        return max(values) - min(values)

    def variance(self) -> float:
        """Population variance over the live window (0 when fewer than 2)."""
        values = self._live()
        n = len(values)
        if n == 0:
            raise EmptyWindowError("cannot compute variance of an empty window")
        if n == 1:
            return 0.0
        mu = sum(values) / n
        return sum((v - mu) ** 2 for v in values) / n

    def snapshot(self) -> dict:
        """Return a summary dict of the current window; safe when empty."""
        if self.is_empty():
            return {"count": 0}
        return {
            "count": self.count(),
            "mean": self.mean(),
            "min": self.min(),
            "max": self.max(),
            "p50": self.percentile(50.0),
            "p95": self.percentile(95.0),
        }

    def clear(self) -> None:
        self._samples.clear()
        self._sum = 0.0
        self._latest_ts = None

    def __len__(self) -> int:
        return self.count()


if __name__ == "__main__":
    stats = RollingStats(window_seconds=10.0)

    for i in range(11):
        stats.add(ts=float(i), value=float(i))

    # window is [1..10] once the newest ts is 10 (t=0 evicted)
    assert stats.count() == 10, stats.count()
    assert stats.min() == 1.0, stats.min()
    assert stats.max() == 10.0, stats.max()
    assert abs(stats.mean() - 5.5) < 1e-9, stats.mean()
    assert abs(stats.median() - 5.5) < 1e-9, stats.median()

    # late-but-in-window insert
    assert stats.add(ts=9.5, value=100.0) is True
    assert stats.max() == 100.0

    # too-old sample rejected
    assert stats.add(ts=-5.0, value=999.0) is False

    print("snapshot:", stats.snapshot())
    print("p90:", round(stats.percentile(90.0), 3))
    print("variance:", round(stats.variance(), 3))

    stats.clear()
    assert stats.is_empty()
    try:
        stats.mean()
    except EmptyWindowError as err:
        print("empty guard:", err)

    print("rolling_stats smoke ok")
