"""LRU cache with per-entry time-to-live.

:class:`LRUTTLCache` combines two eviction pressures: a hard capacity bound that
discards the least-recently-used entry when full, and an optional per-entry TTL
that expires stale values. Expiry is handled both lazily (an expired entry read
via :meth:`get` is treated as a miss and dropped) and eagerly (:meth:`purge_expired`
sweeps everything at once).

Recency is tracked with an ordered mapping so that touching an entry is an O(1)
move-to-front operation. The cache records hit/miss/eviction/expiration counters
that can be read as a snapshot for observability.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Hashable, Iterator, Optional, Tuple


Clock = Callable[[], float]
_MISSING = object()


@dataclass
class _Entry:
    value: Any
    expires_at: Optional[float]  # absolute deadline, or None for immortal

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class CacheStats:
    """Immutable-ish snapshot of counters at a point in time."""

    __slots__ = ("hits", "misses", "evictions", "expirations", "size")

    def __init__(
        self,
        hits: int,
        misses: int,
        evictions: int,
        expirations: int,
        size: int,
    ) -> None:
        self.hits = hits
        self.misses = misses
        self.evictions = evictions
        self.expirations = expirations
        self.size = size

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        total = self.lookups
        return (self.hits / total) if total else 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "size": self.size,
            "hit_rate": round(self.hit_rate, 4),
        }

    def __repr__(self) -> str:
        return (
            f"CacheStats(hits={self.hits}, misses={self.misses}, "
            f"evictions={self.evictions}, expirations={self.expirations}, "
            f"size={self.size}, hit_rate={self.hit_rate:.3f})"
        )


class LRUTTLCache:
    """Bounded LRU cache where entries may carry an independent TTL.

    Parameters
    ----------
    capacity:
        Maximum number of live entries. Must be a positive integer.
    default_ttl:
        Seconds an entry lives when :meth:`set` is called without an explicit
        ``ttl``. ``None`` means entries are immortal unless a per-call ttl is
        provided.
    clock:
        Monotonic time source; injectable for testing. Defaults to
        :func:`time.monotonic`.
    """

    def __init__(
        self,
        capacity: int,
        default_ttl: Optional[float] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if default_ttl is not None and default_ttl <= 0:
            raise ValueError("default_ttl must be positive when provided")

        self._capacity = int(capacity)
        self._default_ttl = default_ttl
        self._clock: Clock = clock if clock is not None else time.monotonic
        self._store: "OrderedDict[Hashable, _Entry]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def _resolve_deadline(self, ttl: Any, now: float) -> Optional[float]:
        if ttl is _MISSING:
            ttl = self._default_ttl
        if ttl is None:
            return None
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        return now + float(ttl)

    def set(self, key: Hashable, value: Any, ttl: Any = _MISSING) -> None:
        """Insert or replace *key*.

        A per-call ``ttl`` (seconds) overrides the cache default; pass ``None``
        explicitly to make this particular entry immortal. Setting an existing
        key refreshes both its value and its recency position.
        """
        now = self._clock()
        deadline = self._resolve_deadline(ttl, now)
        with self._lock:
            if key in self._store:
                entry = self._store[key]
                entry.value = value
                entry.expires_at = deadline
                self._store.move_to_end(key)
            else:
                self._store[key] = _Entry(value=value, expires_at=deadline)
                self._store.move_to_end(key)
                self._enforce_capacity()

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Return the value for *key*, or *default* on a miss.

        A lookup that lands on an expired entry drops that entry and counts as a
        miss. A successful lookup promotes the entry to most-recently-used.
        """
        now = self._clock()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return default
            if entry.is_expired(now):
                del self._store[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """Like :meth:`get` but does not affect recency or hit/miss counters.

        Expired entries are still reported as absent (and lazily removed), but
        no statistics are mutated.
        """
        now = self._clock()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            if entry.is_expired(now):
                del self._store[key]
                self._expirations += 1
                return default
            return entry.value

    def get_or_set(
        self, key: Hashable, factory: Callable[[], Any], ttl: Any = _MISSING
    ) -> Any:
        """Return the cached value for *key*, computing and storing it if absent.

        *factory* is only invoked on a miss (including an expired hit). The
        computation happens outside the lock so a slow factory does not block
        other callers, at the cost of a possible duplicate computation under
        contention (last writer wins).
        """
        sentinel = self.get(key, _MISSING)
        if sentinel is not _MISSING:
            return sentinel
        value = factory()
        self.set(key, value, ttl=ttl)
        return value

    def delete(self, key: Hashable) -> bool:
        """Remove *key* if present. Returns whether anything was deleted."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def _enforce_capacity(self) -> None:
        # Caller must hold the lock.
        while len(self._store) > self._capacity:
            self._store.popitem(last=False)
            self._evictions += 1

    def purge_expired(self) -> int:
        """Eagerly remove every expired entry. Returns the count removed."""
        now = self._clock()
        removed = 0
        with self._lock:
            for key in list(self._store.keys()):
                if self._store[key].is_expired(now):
                    del self._store[key]
                    self._expirations += 1
                    removed += 1
        return removed

    def ttl_remaining(self, key: Hashable) -> Optional[float]:
        """Seconds until *key* expires.

        Returns ``None`` if the key is immortal, and a negative-safe ``0.0`` is
        never returned for a live key. Raises :class:`KeyError` if the key is
        absent or already expired.
        """
        now = self._clock()
        with self._lock:
            entry = self._store.get(key)
            if entry is None or entry.is_expired(now):
                raise KeyError(key)
            if entry.expires_at is None:
                return None
            return entry.expires_at - now

    def clear(self) -> None:
        """Drop all entries. Counters are preserved for lifetime accounting."""
        with self._lock:
            self._store.clear()

    def stats(self) -> CacheStats:
        """Snapshot the counters and current live size."""
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                expirations=self._expirations,
                size=len(self._store),
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, key: Hashable) -> bool:
        return self.peek(key, _MISSING) is not _MISSING

    def keys_by_recency(self) -> Iterator[Hashable]:
        """Yield live keys from least- to most-recently used.

        The list is materialised under the lock so iteration is safe against
        concurrent mutation.
        """
        with self._lock:
            return iter(list(self._store.keys()))

    def items(self) -> Iterator[Tuple[Hashable, Any]]:
        """Yield ``(key, value)`` pairs for non-expired entries, LRU first."""
        now = self._clock()
        with self._lock:
            snapshot = [
                (k, e.value)
                for k, e in self._store.items()
                if not e.is_expired(now)
            ]
        return iter(snapshot)


if __name__ == "__main__":
    ticks = {"t": 0.0}

    def fake_clock() -> float:
        return ticks["t"]

    cache = LRUTTLCache(capacity=3, default_ttl=10.0, clock=fake_clock)

    cache.set("a", 1)
    cache.set("b", 2, ttl=2.0)
    cache.set("c", 3, ttl=None)  # immortal

    print("get a:", cache.get("a"))
    print("b ttl remaining:", cache.ttl_remaining("b"))

    ticks["t"] += 3.0  # 'b' expires
    print("get b after expiry:", cache.get("b"))

    cache.set("d", 4)  # capacity 3 -> LRU eviction of least recent live key
    print("keys by recency:", list(cache.keys_by_recency()))

    computed = cache.get_or_set("e", lambda: 99, ttl=5.0)
    print("get_or_set e:", computed)

    ticks["t"] += 100.0
    print("purged:", cache.purge_expired())
    print("stats:", cache.stats().as_dict())
