#!/usr/bin/env python3
"""Validate the seeded-defect corpus: structure, ids, ranges, oracle-hygiene.

Usage::

    python scripts/validate_corpus.py [CORPUS_ROOT]

Exit status is 0 iff there are no *errors* (warnings never fail the run). Run it
in CI and before every freeze. ``CORPUS_ROOT`` defaults to ``corpus/`` next to
this script's parent (the repo root).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (no install) by putting the package on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.corpus import (  # noqa: E402
    load_corpus,
    validate_corpus,
)


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "corpus"
    if not root.is_dir():
        print(f"error: corpus root not found: {root}", file=sys.stderr)
        return 2

    items = load_corpus(root)
    issues = validate_corpus(root)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    n_defects = sum(len(it.defects) for it in items)
    unconfirmed = sum(len(it.unconfirmed_defect_ids()) for it in items)
    by_type = {t: sum(1 for it in items if it.type == t) for t in ("code", "paper", "spec")}

    for issue in issues:
        print(issue)

    print("-" * 60)
    print(f"items: {len(items)}  (code={by_type['code']} "
          f"paper={by_type['paper']} spec={by_type['spec']})")
    print(f"seeded defects: {n_defects}  (unconfirmed: {unconfirmed})")
    print(f"errors: {len(errors)}   warnings: {len(warnings)}")

    if unconfirmed:
        print(f"note: {unconfirmed} defect(s) still awaiting human oracle confirmation "
              f"- freeze is blocked until these are confirmed.")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
