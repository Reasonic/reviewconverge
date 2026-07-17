#!/usr/bin/env python3
"""Cross-judge agreement — the reliability evidence reviewers ask for.

Given the per-judge decision caches from several *different-family* frontier
judges (Opus 4.8 / GPT-5.5 / DeepSeek V4-Pro), this reports, over the ambiguous
band:

- each judge's agreement + Cohen's κ against the (oracle-derived) gold labels,
- **pairwise inter-judge κ** — three different-family models agreeing is a direct
  answer to the self-preference-bias attack, and
- the **majority-vote matcher's** precision/recall vs gold.

Writes ``matcher_gold/CROSS_JUDGE.md``. Costs nothing — it only reads caches.

Usage::

    python scripts/matcher_cross_judge.py \\
        deepseek=runs/_scratch/matcher_cache_deepseek.json \\
        opus=runs/_scratch/matcher_cache_opus.json \\
        gpt55=runs/_scratch/matcher_cache_gpt55.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.matcher.cache import DecisionCache  # noqa: E402
from reviewconverge.matcher.validation import (  # noqa: E402
    PRReport,
    band_pairs,
    band_verdicts,
    cohen_kappa,
    load_gold_jsonl,
)

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "matcher_gold"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Cross-judge agreement over judge caches.")
    ap.add_argument("judges", nargs="+", metavar="LABEL=CACHE.json")
    ap.add_argument("--gold", default=str(GOLD / "pairs.jsonl"))
    args = ap.parse_args(argv[1:])

    pairs = load_gold_jsonl(Path(args.gold))
    band = band_pairs(pairs)
    gold = {p.pair_id: p.label for p in band}

    judges: dict[str, DecisionCache] = {}
    for spec in args.judges:
        label, _, path = spec.partition("=")
        if not path:
            print(f"error: bad judge spec {spec!r} (want LABEL=CACHE.json)", file=sys.stderr)
            return 2
        judges[label] = DecisionCache.load(Path(path))
    labels = list(judges)
    verdicts = {lab: band_verdicts(band, c) for lab, c in judges.items()}

    common = [p for p in band if all(verdicts[lab][p.pair_id] is not None for lab in labels)]
    if not common:
        print("error: no band pairs decided by ALL judges (run the judges first).", file=sys.stderr)
        return 2

    lines: list[str] = ["# Cross-judge agreement (matcher reliability)", ""]
    lines.append(f"Band pairs: {len(band)}; decided by all {len(labels)} judges: {len(common)}.")
    lines += ["", "## Per-judge vs gold (oracle-derived labels)", "",
              "| judge | agreement | κ vs gold |", "|---|---|---|"]
    print(f"band pairs: {len(band)}; decided by all {len(labels)}: {len(common)}")
    for lab in labels:
        a = [verdicts[lab][p.pair_id] for p in common]
        g = [gold[p.pair_id] for p in common]
        agree = sum(x == y for x, y in zip(a, g)) / len(common)
        k = cohen_kappa(a, g)
        lines.append(f"| {lab} | {agree:.4f} | {k:.4f} |")
        print(f"  {lab}: agreement {agree:.4f}, κ vs gold {k:.4f}")

    lines += ["", "## Inter-judge κ (pairwise, different families)", "",
              "| judge A | judge B | κ |", "|---|---|---|"]
    print("inter-judge κ:")
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            a = [verdicts[labels[i]][p.pair_id] for p in common]
            b = [verdicts[labels[j]][p.pair_id] for p in common]
            k = cohen_kappa(a, b)
            lines.append(f"| {labels[i]} | {labels[j]} | {k:.4f} |")
            print(f"  {labels[i]} vs {labels[j]}: {k:.4f}")

    tp = fp = fn = tn = 0
    for p in common:
        votes = [verdicts[lab][p.pair_id] for lab in labels]
        maj = sum(votes) * 2 > len(votes)
        lbl = gold[p.pair_id]
        if maj and lbl:
            tp += 1
        elif maj and not lbl:
            fp += 1
        elif not maj and lbl:
            fn += 1
        else:
            tn += 1
    rep = PRReport(len(common), tp, fp, fn, tn).to_dict()
    lines += ["", f"## Majority-vote matcher ({len(labels)} judges, band)", "",
              "| precision | recall | F1 | accuracy |", "|---|---|---|---|",
              f"| {rep['precision']} | {rep['recall']} | {rep['f1']} | {rep['accuracy']} |", ""]
    print(f"majority-vote matcher: P {rep['precision']} R {rep['recall']} F1 {rep['f1']}")

    out = GOLD / "CROSS_JUDGE.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
