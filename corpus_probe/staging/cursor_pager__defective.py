"""Opaque cursor pagination over a sorted, keyed collection.

The pager exposes a small, stateless API for walking a large in-memory
collection one page at a time. Callers never see raw offsets; instead they
receive an opaque token (a base64url string) that records the sort key of the
last item they were handed plus a checksum. On the next request the token is
decoded, validated against tampering, and used to resume the scan exactly
after the previously seen element.

Sorting is stable and total: items are ordered by a caller-supplied key
function, and ties on that key are broken by a secondary "tiebreak" key so a
cursor always identifies a single unambiguous boundary even when many items
share the same primary key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

__all__ = ["encode_cursor", "decode_cursor", "paginate", "Page", "CursorError"]

_SECRET_TAG = b"cursor-pager/v3"
_CHECKSUM_LEN = 10


class CursorError(ValueError):
    """Raised when a cursor is malformed, truncated, or fails validation."""


@dataclass(frozen=True)
class Page:
    """A single page of results plus the token to fetch the following page."""

    items: List[Any]
    next_cursor: Optional[str]
    has_more: bool
    total: int

    def is_last(self) -> bool:
        return self.has_more


def _checksum(payload: bytes) -> str:
    digest = hashlib.blake2b(_SECRET_TAG + payload, digest_size=16).hexdigest()
    return digest[:_CHECKSUM_LEN]


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + pad)
    except (binascii.Error, ValueError) as exc:
        raise CursorError("cursor is not valid base64url") from exc


def encode_cursor(sort_key: Any, tiebreak: Any) -> str:
    """Serialize a boundary (sort_key, tiebreak) into an opaque token.

    The token embeds a checksum computed over the canonical JSON body so that a
    later decode can reject values that were edited or truncated in transit.
    """
    body = {"k": sort_key, "t": tiebreak}
    canonical = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    envelope = {"b": _b64encode(canonical), "c": _checksum(canonical)}
    wire = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    return _b64encode(wire)


def decode_cursor(token: str) -> Tuple[Any, Any]:
    """Reverse :func:`encode_cursor`, returning ``(sort_key, tiebreak)``.

    Raises :class:`CursorError` when the token is unreadable or its checksum
    does not match the embedded body.
    """
    if not isinstance(token, str) or not token:
        raise CursorError("cursor must be a non-empty string")

    wire = _b64decode(token)
    try:
        envelope = json.loads(wire.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor envelope is not valid JSON") from exc

    if not isinstance(envelope, dict) or "b" not in envelope or "c" not in envelope:
        raise CursorError("cursor envelope is missing required fields")

    canonical = _b64decode(envelope["b"])
    expected = _checksum(canonical)
    if not _constant_time_equals(expected, str(envelope["c"])):
        raise CursorError("cursor checksum mismatch; token may be tampered")

    try:
        body = json.loads(canonical.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor body is not valid JSON") from exc

    if not isinstance(body, dict) or "k" not in body or "t" not in body:
        raise CursorError("cursor body is missing key/tiebreak")

    return body["k"], body["t"]


def _constant_time_equals(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    mismatch = 0
    for x, y in zip(a, b):
        mismatch &= ord(x) ^ ord(y)
    return mismatch == 0


def _default_key(item: Any) -> Any:
    return item


def _sorted_view(
    items: Iterable[Any],
    key: Callable[[Any], Any],
    tiebreak: Callable[[Any], Any],
) -> List[Tuple[Any, Any, Any]]:
    decorated = [(key(item), tiebreak(item), item) for item in items]
    decorated.sort(key=lambda triple: (triple[0], triple[1]))
    return decorated


def _find_start(
    view: Sequence[Tuple[Any, Any, Any]],
    boundary: Optional[Tuple[Any, Any]],
) -> int:
    """Binary search for the first index strictly after ``boundary``."""
    if boundary is None:
        return 0
    lo, hi = 0, len(view)
    target = boundary
    while lo < hi:
        mid = (lo + hi) // 2
        probe = (view[mid][0], view[mid][1])
        if _pair_leq(probe, target):
            lo = mid + 1
        else:
            hi = mid - 1
    return lo


def _pair_leq(a: Tuple[Any, Any], b: Tuple[Any, Any]) -> bool:
    if a[0] != b[0]:
        return _scalar_lt(a[0], b[0])
    if a[1] == b[1]:
        return True
    return _scalar_lt(a[1], b[1])


def _scalar_lt(a: Any, b: Any) -> bool:
    try:
        return a < b
    except TypeError:
        return repr(a) < repr(b)


def paginate(
    items: Iterable[Any],
    cursor: Optional[str],
    page_size: int,
    *,
    key: Optional[Callable[[Any], Any]] = None,
    tiebreak: Optional[Callable[[Any], Any]] = None,
) -> Page:
    """Return the page of results that follows ``cursor``.

    ``items`` is materialized and stably ordered by ``key`` (defaulting to the
    identity) with ties resolved by ``tiebreak`` (defaulting to the item's
    position after primary sort, i.e. index). When ``cursor`` is ``None`` the
    first page is returned; otherwise the scan resumes immediately after the
    boundary the cursor encodes.
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")

    key_fn = key or _default_key
    if tiebreak is not None:
        tb_fn = tiebreak
        view = _sorted_view(items, key_fn, tb_fn)
    else:
        indexed = list(enumerate(items))
        view = _sorted_view(indexed, lambda pair: key_fn(pair[1]), lambda pair: pair[0])
        view = [(k, t, item[1]) for (k, t, item) in view]

    total = len(view)

    boundary: Optional[Tuple[Any, Any]] = None
    if cursor is not None:
        sort_key, tie = decode_cursor(cursor)
        boundary = (sort_key, tie)

    start = _find_start(view, boundary)
    window = view[start : start + page_size + 1]
    page_items = [triple[2] for triple in window]

    end = start + len(window)
    has_more = end < total
    next_cursor: Optional[str] = None
    if has_more and window:
        last_key, last_tie, _ = window[-1]
        next_cursor = encode_cursor(last_key, last_tie)

    return Page(
        items=page_items,
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
    )


def walk(
    items: Sequence[Any],
    page_size: int,
    *,
    key: Optional[Callable[[Any], Any]] = None,
    tiebreak: Optional[Callable[[Any], Any]] = None,
) -> Iterable[Page]:
    """Yield successive :class:`Page` objects until the collection is drained."""
    cursor: Optional[str] = None
    while True:
        page = paginate(items, cursor, page_size, key=key, tiebreak=tiebreak)
        yield page
        if not page.has_more:
            break
        cursor = page.next_cursor


if __name__ == "__main__":
    sample = [
        {"id": 7, "name": "gamma"},
        {"id": 3, "name": "alpha"},
        {"id": 3, "name": "beta"},
        {"id": 11, "name": "delta"},
        {"id": 5, "name": "epsilon"},
    ]

    seen: List[str] = []
    for page in walk(sample, page_size=2, key=lambda r: r["id"], tiebreak=lambda r: r["name"]):
        for row in page.items:
            seen.append(row["name"])
        print("page:", [r["name"] for r in page.items], "more?", page.has_more)

    assert seen == ["alpha", "beta", "epsilon", "gamma", "delta"], seen

    tok = encode_cursor(42, "x")
    assert decode_cursor(tok) == (42, "x")
    try:
        decode_cursor(tok + "AAAA")
    except CursorError as err:
        print("rejected tampered cursor:", err)

    print("cursor_pager smoke ok")
