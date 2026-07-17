#!/usr/bin/env python3
"""Finalize the realistic-scale probe corpus after the human R/F/U audit (2026-07-12).

The maintainer (non-author) audited all seeded defects and the gray zones. Result:
  * all 39 seeded defects confirmed Real / Findable / Unique / Independent -> confirmed:true
  * 7/10 gray zones confirmed correctly-excluded (left as-is)
  * cron.py:213 gray zone: KEPT (entangled with probe-0001-d2 + Vixie-defensible) -> unchanged
  * lru_ttl_cache.py:262 and retry.py:70: judged real bugs -> PROMOTED to seeded defects
    (removed from known_gray_zone; artifact bytes are UNCHANGED, only labels move).

Idempotent: re-running will not double-add the promoted defects. After this, the
corpus validates with every defect confirmed, so `freeze_corpus.py freeze corpus_probe`
will succeed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "corpus_probe" / "code"
AUDIT_DATE = "2026-07-12"

# Defects promoted from flagged gray zones. Keyed by item id.
PROMOTIONS = {
    "probe-0005": {
        "gray_line": 262,  # remove the known_gray_zone entry at this line
        "transformation": "impure-membership-side-effect",
        "defect": {
            "id": "probe-0005-d5",
            "category": "impure-membership-side-effect",
            "severity": "major",
            "description": (
                "`__contains__` delegates to `peek()`, which lazily evicts an expired "
                "entry and increments the `_expirations` counter, so a plain membership "
                "test (`key in cache`) mutates cache contents and observability statistics "
                "as a side effect instead of being read-only."
            ),
            "location": {"unit": "src/lru_ttl_cache.py", "start": 262, "end": 263},
            "anchor": "self.peek(key, _MISSING)",
            "paraphrases": [
                "Membership testing is not side-effect-free: `key in cache` can delete an "
                "expired entry and bump the expiration counter because `__contains__` calls "
                "the mutating `peek()`.",
                "Because `__contains__` routes through `peek`, repeatedly checking "
                "`key in cache` changes `_expirations` and can evict entries, so containment "
                "checks are observably impure.",
                "A read-only `in` check unexpectedly mutates state here — `__contains__` "
                "should test presence/liveness without removing keys or updating statistics.",
            ],
            "confirmed": True,
            "rationale": (
                "Correct form: `__contains__` tests key presence and liveness without "
                "evicting or touching `_expirations` (no call into the mutating peek()). "
                f"Human R/F/U-audited & confirmed {AUDIT_DATE} (promoted from a flagged gray zone)."
            ),
        },
    },
    "probe-0006": {
        "gray_line": 70,
        "transformation": "missing-input-validation",
        "defect": {
            "id": "probe-0006-d5",
            "category": "missing-input-validation",
            "severity": "minor",
            "description": (
                "`_normalize_exc_types` does `tuple(exc)` on any iterable without checking "
                "its elements are exception classes, so a malformed `retry_on` (e.g. a list "
                "containing non-exception values) is accepted silently at construction and "
                "only fails much later as a `TypeError` inside `isinstance()` during matching."
            ),
            "location": {"unit": "src/retry.py", "start": 70, "end": 70},
            "anchor": "return tuple(exc)",
            "paraphrases": [
                "No validation that `retry_on` elements are exception types: `tuple(exc)` "
                "accepts arbitrary objects, deferring the failure to a confusing `TypeError` "
                "inside `isinstance` at retry time.",
                "A `retry_on` iterable containing non-exception objects is silently accepted "
                "here and only errors later during exception matching, rather than being "
                "rejected at construction.",
                "`_normalize_exc_types` should reject non-exception-class elements up front, "
                "but blindly builds the tuple, so malformed input surfaces as a late, opaque "
                "`isinstance()` error.",
            ],
            "confirmed": True,
            "rationale": (
                "Correct form: validate each element is a BaseException subclass and raise at "
                "construction, e.g. `types = tuple(exc); if not all(isinstance(t, type) and "
                "issubclass(t, BaseException) for t in types): raise TypeError(...); return types`. "
                f"Human R/F/U-audited & confirmed {AUDIT_DATE} (promoted from a flagged gray zone)."
            ),
        },
    },
}

PENDING = "PENDING human R/F/U audit"
AUDITED_D = f"human R/F/U-audited & confirmed {AUDIT_DATE}"
AUDITED_P = (f"freshly authored (LLM) + LLM-seeded defects; human R/F/U-audited "
             f"& confirmed {AUDIT_DATE}")


def main() -> int:
    items = sorted(p.name for p in CODE.glob("probe-*") if p.is_dir())
    total_defects = 0
    for pid in items:
        ddir = CODE / pid
        defects_path = ddir / "defects.json"
        meta_path = ddir / "meta.json"
        dj = json.loads(defects_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        # 1) confirm every existing defect + refresh its provenance line
        for d in dj["defects"]:
            d["confirmed"] = True
            if isinstance(d.get("rationale"), str):
                d["rationale"] = d["rationale"].replace(PENDING, AUDITED_D)

        # 2) promotions
        if pid in PROMOTIONS:
            spec = PROMOTIONS[pid]
            have = {d["id"] for d in dj["defects"]}
            if spec["defect"]["id"] not in have:
                dj["defects"].append(spec["defect"])
            # drop the promoted gray zone (match by line)
            gl = spec["gray_line"]
            meta["known_gray_zone"] = [
                z for z in meta.get("known_gray_zone", [])
                if z.get("location", {}).get("start") != gl
            ]
            tr = set(meta.get("construction", {}).get("transformations", []))
            tr.add(spec["transformation"])
            meta.setdefault("construction", {})["transformations"] = sorted(tr)

        # 3) meta provenance + defect_count
        meta["defect_count"] = len(dj["defects"])
        constr = meta.setdefault("construction", {})
        if isinstance(constr.get("proposer"), str):
            constr["proposer"] = AUDITED_P
        if isinstance(meta.get("source", {}).get("notes"), str):
            meta["source"]["notes"] = meta["source"]["notes"].replace(
                "defects seeded then human-audited",
                f"defects seeded then human R/F/U-audited & confirmed {AUDIT_DATE}",
            )

        defects_path.write_text(json.dumps(dj, indent=1) + "\n", encoding="utf-8")
        meta_path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
        ng = len(meta.get("known_gray_zone", []))
        total_defects += len(dj["defects"])
        promoted = " (+1 promoted)" if pid in PROMOTIONS else ""
        print(f"{pid}: {len(dj['defects'])} defects{promoted}, {ng} gray zone(s)")

    print(f"\ntotal seeded defects: {total_defects}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
