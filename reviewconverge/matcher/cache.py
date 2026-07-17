"""Content-addressed decision cache — the matcher's determinism guarantee.

Current frontier models reject ``temperature`` and ``temperature=0`` never
guaranteed determinism anyway (PLANS §4.3a.4). So determinism does not come from
the sampler; it comes from *here*: every ``(finding_a, finding_b)`` equivalence
verdict is decided once and cached, keyed by the **content** of the two findings
(not their transient per-run ids). Re-running the matcher — or matching a pair
that recurs across rounds/runs — replays the cached verdict instead of asking the
model again. That makes the pipeline deterministic-by-construction regardless of
model non-determinism, and (as a bonus) collapses the paid LLM-judgment count.

The key is order-independent: ``match(a, b) == match(b, a)`` by construction.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Optional

from ..schema import Location
from .similarity import normalize


def finding_fingerprint(
    text: str, location: Optional[Location], scope: str = "", keep_operators: bool = False
) -> str:
    """A stable content hash for one finding side.

    Uses the normalized claim text plus the location's ``unit`` (but *not* the
    exact offsets: paraphrases of the same issue may localize slightly
    differently, and the verdict should not churn on a one-line shift). Two
    findings with the same normalized wording and unit share a fingerprint.

    ``scope`` optionally namespaces the fingerprint by artifact id. The decision
    cache is shared across artifacts and keyed purely by content, so two *different*
    artifacts that share a ``unit`` name (``main.py``, a section id) and a normalized
    claim would otherwise collide — a verdict decided in artifact A would replay in
    artifact B without the judge (audit #4). Passing ``scope=artifact_id`` isolates
    them. **Default is empty** (unscoped), which reproduces the original key exactly:
    activating scopes changes every key, so a warm decision cache built unscoped must
    be re-judged. On the frozen corpus this bleed is provably absent (0 cross-artifact
    pair-keys), so the unscoped warm cache is valid there; use a scope for new/mixed
    corpora where a name collision is possible.
    """
    unit = location.unit if location is not None else ""
    payload = f"{normalize(text, keep_operators=keep_operators)}␟{unit.strip().lower()}"
    if scope:
        payload = f"{scope.strip().lower()}␟{payload}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def pair_key(fp_a: str, fp_b: str) -> str:
    """Order-independent key for a fingerprint pair."""
    lo, hi = sorted((fp_a, fp_b))
    return f"{lo}:{hi}"


class DecisionCache:
    """A persistent, order-independent map from finding-pairs to verdicts.

    Values are ``True`` (same issue) / ``False`` (different). Backed by a flat
    JSON file so a frozen cache can be shipped in ``runs/`` for exact
    reproducibility of every reported number.
    """

    def __init__(self, entries: Optional[dict[str, bool]] = None) -> None:
        self._d: dict[str, bool] = dict(entries or {})
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()  # allows shared use across worker threads

    # -- lookup -----------------------------------------------------------
    def get(self, fp_a: str, fp_b: str) -> Optional[bool]:
        with self._lock:
            v = self._d.get(pair_key(fp_a, fp_b))
            if v is None:
                self.misses += 1
            else:
                self.hits += 1
            return v

    def put(self, fp_a: str, fp_b: str, verdict: bool) -> None:
        with self._lock:
            self._d[pair_key(fp_a, fp_b)] = verdict

    def copy(self) -> "DecisionCache":
        """A detached copy — used to score without mutating the real judge cache."""
        with self._lock:
            return DecisionCache(dict(self._d))

    def __len__(self) -> int:
        return len(self._d)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return pair_key(*key) in self._d

    # -- persistence ------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "DecisionCache":
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("verdicts", {}))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            snapshot = dict(self._d)
        # Sorted keys → stable file bytes → diffable, hashable, drift-checkable.
        body = {"verdicts": {k: snapshot[k] for k in sorted(snapshot)}}
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
