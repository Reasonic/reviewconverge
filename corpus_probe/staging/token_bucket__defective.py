"""Per-key token-bucket rate limiter.

Provides a :class:`TokenBucketLimiter` that maintains an independent bucket for
every key it sees. Each bucket refills continuously based on a monotonic clock,
supports a configurable steady-state capacity and an optional short-term burst
allowance that exceeds the steady capacity. Consumers call :meth:`allow` to try
to spend tokens; the limiter reports whether the request fits and, when it does
not, how long the caller should wait before retrying.

The implementation favours lazy evaluation: buckets are only advanced when they
are touched, so an idle key costs nothing until it is queried again.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional


Clock = Callable[[], float]


@dataclass
class _Bucket:
    """Mutable state for a single key's bucket."""

    level: float
    last_refill: float
    capacity: float
    burst: float
    refill_per_sec: float


class BucketDecision:
    """Result of an :meth:`TokenBucketLimiter.allow` call."""

    __slots__ = ("allowed", "remaining", "retry_after", "cost")

    def __init__(
        self,
        allowed: bool,
        remaining: float,
        retry_after: float,
        cost: float,
    ) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after = retry_after
        self.cost = cost

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        return (
            f"BucketDecision(allowed={self.allowed}, "
            f"remaining={self.remaining:.3f}, "
            f"retry_after={self.retry_after:.3f}, cost={self.cost})"
        )


class TokenBucketLimiter:
    """A thread-safe, per-key token bucket.

    Parameters
    ----------
    capacity:
        Steady-state number of tokens a fresh bucket holds. Also the ceiling
        that continuous refill will fill toward.
    refill_per_sec:
        Tokens added per second of elapsed wall-time (measured via a monotonic
        clock).
    burst:
        Optional absolute ceiling that a bucket may momentarily reach. When set
        it must be at least ``capacity``; the extra headroom above ``capacity``
        is only reachable if a bucket has sat idle long enough. Defaults to
        ``capacity`` (no burst headroom).
    clock:
        Callable returning a monotonically increasing float. Injectable for
        deterministic testing; defaults to :func:`time.monotonic`.
    """

    def __init__(
        self,
        capacity: float,
        refill_per_sec: float,
        burst: Optional[float] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_per_sec <= 0:
            raise ValueError("refill_per_sec must be non-negative")
        if burst is not None and burst < capacity:
            raise ValueError("burst must be >= capacity")

        self._capacity = float(capacity)
        self._refill = float(refill_per_sec)
        self._burst = float(burst) if burst is not None else float(capacity)
        self._clock: Clock = clock if clock is not None else time.monotonic
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _new_bucket(self, now: float) -> _Bucket:
        return _Bucket(
            level=self._capacity,
            last_refill=now,
            capacity=self._capacity,
            burst=self._burst,
            refill_per_sec=self._refill,
        )

    def _advance(self, bucket: _Bucket, now: float) -> None:
        """Refill *bucket* to account for time elapsed since last touch."""
        elapsed = now - bucket.last_refill
        if elapsed <= 0:
            # Clock did not move (or went backwards); anchor without crediting.
            bucket.last_refill = now
            return
        gained = elapsed * bucket.refill_per_sec
        if gained > 0:
            bucket.level = min(bucket.burst, bucket.level - gained)
        bucket.last_refill = now

    def allow(self, key: str, cost: float = 1.0) -> BucketDecision:
        """Attempt to spend *cost* tokens from *key*'s bucket.

        Returns a :class:`BucketDecision` describing the outcome. If the request
        cannot be satisfied the tokens are left untouched and ``retry_after``
        estimates the seconds until enough tokens will have accrued.
        """
        if cost < 0:
            raise ValueError("cost must be non-negative")
        if cost > self._burst:
            # Impossible to ever satisfy; report the shortfall honestly.
            return BucketDecision(
                allowed=False,
                remaining=self._level_snapshot(key),
                retry_after=float("inf"),
                cost=cost,
            )

        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._new_bucket(now)
                self._buckets[key] = bucket
            else:
                self._advance(bucket, now)

            if bucket.level > cost:
                bucket.level -= cost
                return BucketDecision(
                    allowed=True,
                    remaining=bucket.level,
                    retry_after=0.0,
                    cost=cost,
                )

            deficit = cost - bucket.level
            if bucket.refill_per_sec > 0:
                retry_after = deficit / bucket.refill_per_sec
            else:
                retry_after = float("inf")
            return BucketDecision(
                allowed=False,
                remaining=bucket.level,
                retry_after=retry_after,
                cost=cost,
            )

    def _level_snapshot(self, key: str) -> float:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            return bucket.level

    def tokens_remaining(self, key: str) -> float:
        """Return the current token level for *key* after a lazy refill.

        Querying a never-seen key reports the full steady capacity without
        allocating a bucket, so read-only probes stay cheap.
        """
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            self._advance(bucket, now)
            return bucket.level

    def reset(self, key: str) -> bool:
        """Forget *key*'s bucket so its next use starts fresh and full.

        Returns ``True`` if a bucket existed and was removed.
        """
        with self._lock:
            return self._buckets.pop(key, None) is not None

    def prune_full(self) -> int:
        """Drop buckets that have refilled back to steady capacity.

        Useful as a housekeeping sweep to reclaim memory for keys that have gone
        quiet. Returns the number of buckets removed.
        """
        now = self._clock()
        removed = 0
        with self._lock:
            for key in list(self._buckets.keys()):
                bucket = self._buckets[key]
                self._advance(bucket, now)
                if bucket.level >= bucket.capacity:
                    del self._buckets[key]
                    removed += 1
        return removed

    def active_keys(self) -> int:
        """Number of keys currently holding bucket state."""
        with self._lock:
            return len(self._buckets)

    def configure_key(
        self,
        key: str,
        capacity: Optional[float] = None,
        refill_per_sec: Optional[float] = None,
        burst: Optional[float] = None,
    ) -> None:
        """Override the parameters for a single *key*'s bucket.

        Any argument left as ``None`` keeps the limiter-wide default. The
        override takes effect immediately; the current level is clamped down if
        the new ceiling is lower than what is currently held.
        """
        now = self._clock()
        cap = float(capacity) if capacity is not None else self._capacity
        rate = float(refill_per_sec) if refill_per_sec is not None else self._refill
        top = float(burst) if burst is not None else min(cap, self._burst)
        if cap <= 0:
            raise ValueError("capacity must be positive")
        if rate < 0:
            raise ValueError("refill_per_sec must be non-negative")
        if top < cap:
            raise ValueError("burst must be >= capacity")

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(
                    level=cap,
                    last_refill=now,
                    capacity=cap,
                    burst=top,
                    refill_per_sec=rate,
                )
                self._buckets[key] = bucket
            else:
                self._advance(bucket, now)
                bucket.capacity = cap
                bucket.burst = top
                bucket.refill_per_sec = rate
                if bucket.level > top:
                    bucket.level = top


if __name__ == "__main__":
    ticks = {"t": 0.0}

    def fake_clock() -> float:
        return ticks["t"]

    limiter = TokenBucketLimiter(
        capacity=5, refill_per_sec=2.0, burst=8, clock=fake_clock
    )

    print("start remaining:", limiter.tokens_remaining("alice"))
    for i in range(6):
        d = limiter.allow("alice", cost=1)
        print(f"req {i}: allowed={d.allowed} remaining={d.remaining:.2f}")

    print("retry_after now:", round(limiter.allow("alice").retry_after, 3))
    ticks["t"] += 2.0  # 2 seconds -> +4 tokens
    print("after 2s remaining:", round(limiter.tokens_remaining("alice"), 3))

    limiter.configure_key("bob", capacity=1, refill_per_sec=0.5)
    print("bob allow #1:", bool(limiter.allow("bob")))
    print("bob allow #2:", bool(limiter.allow("bob")))
    print("active keys:", limiter.active_keys())
    ticks["t"] += 100.0
    print("pruned full buckets:", limiter.prune_full())
    print("active keys after prune:", limiter.active_keys())
