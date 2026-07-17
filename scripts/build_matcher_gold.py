#!/usr/bin/env python3
"""Build the matcher gold set from the frozen oracle.

Derives labeled finding pairs (same/different issue) from the seeded-defect
corpus and writes them to ``matcher_gold/pairs.jsonl``:

- positives  = paraphrase pairs of one defect (the oracle authored them as "same"),
- hard negs  = distinct-defect pairs within one artifact (share context/location),
- easy negs  = distinct-defect pairs across artifacts (deterministic, class-balanced).

These are the ground-truth labels the matcher is scored against (see
``scripts/validate_matcher.py``). Independent human + frontier second-opinion
labels for κ are layered on top of the same pair ids afterward.

Usage::

    python scripts/build_matcher_gold.py [CORPUS_ROOT] [--sample N] [--seed S]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.corpus import load_corpus  # noqa: E402
from reviewconverge.matcher.validation import build_gold_from_corpus, write_gold_jsonl  # noqa: E402


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = {a.split("=")[0]: a.split("=")[1] for a in argv[1:] if a.startswith("--") and "=" in a}
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "corpus"
    out = Path(__file__).resolve().parent.parent / "matcher_gold" / "pairs.jsonl"
    sample = int(opts["--sample"]) if "--sample" in opts else None
    seed = int(opts.get("--seed", "0"))

    if not root.is_dir():
        print(f"error: corpus root not found: {root}", file=sys.stderr)
        return 2

    items = load_corpus(root)
    pairs = build_gold_from_corpus(items, sample=sample, seed=seed)
    write_gold_jsonl(pairs, out)

    pos = sum(1 for p in pairs if p.label)
    neg = len(pairs) - pos
    by_source: dict[str, int] = {}
    for p in pairs:
        by_source[p.source] = by_source.get(p.source, 0) + 1

    print(f"wrote {len(pairs)} gold pairs -> {out}")
    print(f"  same (positive): {pos}")
    print(f"  different (negative): {neg}")
    for s in sorted(by_source):
        print(f"  {s}: {by_source[s]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
