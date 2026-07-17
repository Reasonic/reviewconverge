#!/usr/bin/env python3
"""Score a labeled on-distribution worksheet against the matcher (audit R2-M1).

Reads the human-labeled ``worksheet.csv`` (``human_same`` filled Y/N) and the held-out
``key.jsonl`` (matcher verdicts + provenance), and reports **matcher-vs-human agreement,
Cohen's κ, and matcher error broken out per arm and per pair type** — the deployed-
distribution validation the κ = 1.00 constructed-pair check does not provide.

The headline the reviewers want: is the matcher's error rate (esp. on nomem
leave-and-return pairs, which drive churn) low and **balanced across arms**? If it is,
the memory→convergence dynamics are not a matching artifact.

Usage::  python scripts/score_ondist.py matcher_gold/ondist
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from math import comb
from pathlib import Path


def cohen_kappa(pairs):
    """pairs: list of (a_bool, b_bool)."""
    n = len(pairs)
    if not n:
        return float("nan")
    po = sum(1 for a, b in pairs if a == b) / n
    pa1 = sum(1 for a, _ in pairs if a) / n
    pb1 = sum(1 for _, b in pairs if b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - m) / d, (c + m) / d)


def main(argv):
    d = Path(argv[1] if len(argv) > 1 else "matcher_gold/ondist")
    key = {r["row_id"]: r for r in (json.loads(l) for l in (d / "key.jsonl").read_text().splitlines() if l.strip())}

    labeled = []
    with (d / "worksheet.csv").open() as fh:
        for row in csv.DictReader(fh):
            v = (row.get("human_same (Y/N)") or "").strip().upper()
            if v in ("Y", "N"):
                labeled.append((row["row_id"], v == "Y"))
    if not labeled:
        print("No labels found yet. Fill the `human_same (Y/N)` column in worksheet.csv with Y/N, then re-run.")
        return 1

    groups = defaultdict(list)  # (pair_type, arm) -> [(human, matcher)]
    overall = []
    for rid, human in labeled:
        k = key.get(rid)
        if not k:
            continue
        m = bool(k["matcher_same"])
        groups[(k["pair_type"], k["arm"])].append((human, m))
        overall.append((human, m))

    print(f"labeled {len(labeled)} / {len(key)} rows\n")
    print(f"{'group':34} {'n':>4} {'agree':>7} {'kappa':>7}  matcher-error [95% CI]")
    def report(name, pairs):
        n = len(pairs)
        if not n:
            return
        agree = sum(1 for h, m in pairs if h == m)
        err = n - agree
        lo, hi = wilson(err, n)
        print(f"{name:34} {n:>4} {agree/n:>7.3f} {cohen_kappa(pairs):>7.3f}  "
              f"{err/n:.3f} [{lo:.3f},{hi:.3f}]")

    for (pt, arm), pairs in sorted(groups.items()):
        report(f"{pt} / {arm}", pairs)
    print("-" * 70)
    # per-arm (both types) and per-type (both arms)
    per_arm = defaultdict(list)
    per_type = defaultdict(list)
    for (pt, arm), pairs in groups.items():
        per_arm[arm] += pairs
        per_type[pt] += pairs
    for arm, pairs in sorted(per_arm.items()):
        report(f"ALL / {arm}", pairs)
    for pt, pairs in sorted(per_type.items()):
        report(f"{pt} / ALL", pairs)
    report("OVERALL", overall)
    print("\nInterpretation: low, arm-balanced matcher error (esp. leave_and_return, which drives\n"
          "nomem churn) ⇒ the memory→convergence dynamics are not a matching artifact (§7).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
