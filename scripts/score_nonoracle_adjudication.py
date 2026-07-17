#!/usr/bin/env python3
"""Score a completed non-oracle adjudication → rho per arm → corrected probe terminal-F1 gap.

Reads the exported `nonoracle_adjudication_result.json` (from NONORACLE_ADJUDICATION.html) and
computes, per arm, rho = occurrence-weighted fraction of retained non-oracle findings judged REAL.
Then it recredits a rho fraction of each arm's non-oracle terminal findings as true and recomputes
mean terminal precision (recall held at the observed value — real *unseeded* defects the loop *found*
do not change recall against the seeded oracle) and the per-arm F1, reporting the corrected mem−nomem
gap. Settles whether the reported reversal (−0.089 under seeded-only scoring) is real or an artifact.

Observed probe terminals (from probe_results, seeded-oracle scoring):
    mem : precision 0.654, recall 0.937   nomem: precision 0.838, recall 0.880
    per-run mean F1: mem 0.760, nomem 0.849  →  gap −0.089

Usage:  python scripts/score_nonoracle_adjudication.py nonoracle_adjudication_result.json
"""
import json
import sys
from collections import defaultdict

# observed seeded-oracle terminals (probe_results/probe_analysis.json)
OBS = {"memory": {"p": 0.654, "r": 0.937, "f1": 0.760},
       "no-memory": {"p": 0.838, "r": 0.880, "f1": 0.849}}


def f1(p, r):
    return 2 * p * r / (p + r) if (p + r) else 0.0


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: score_nonoracle_adjudication.py <exported_result.json>")
    d = json.load(open(sys.argv[1]))
    items = d.get("items", d)
    w_real, w_unsure, w_tot = defaultdict(float), defaultdict(float), defaultdict(float)
    n_done = n_tot = 0
    for it in items.values():
        arm, wt, v = it["arm"], float(it.get("weight", 1)), it.get("verdict")
        n_tot += 1
        w_tot[arm] += wt
        if v:
            n_done += 1
        if v == "real":
            w_real[arm] += wt
        elif v == "unsure":
            w_unsure[arm] += wt

    print(f"adjudicated {n_done}/{n_tot} unique findings\n")
    print(f"{'arm':<11} {'rho_real':>9} {'rho_+half_unsure':>17} {'corr.prec':>10} {'corr.F1':>9}")
    corr = {}
    for arm in ("memory", "no-memory"):
        tot = w_tot[arm] or 1
        rho = w_real[arm] / tot
        rho_hi = (w_real[arm] + 0.5 * w_unsure[arm]) / tot
        p2 = OBS[arm]["p"] + rho * (1 - OBS[arm]["p"])          # credit rho of the false findings
        f = f1(p2, OBS[arm]["r"])
        corr[arm] = {"rho": rho, "rho_hi": rho_hi, "p": p2, "f1": f}
        print(f"{arm:<11} {rho:>9.3f} {rho_hi:>17.3f} {p2:>10.3f} {f:>9.3f}")

    gap0 = OBS["memory"]["f1"] - OBS["no-memory"]["f1"]
    gap = corr["memory"]["f1"] - corr["no-memory"]["f1"]
    print(f"\nseeded-oracle F1 gap (mem − nomem): {gap0:+.3f}  (the reported reversal)")
    print(f"rho-corrected  F1 gap (mem − nomem): {gap:+.3f}")
    if gap < -0.03:
        verdict = "REVERSAL SURVIVES — memory is worse on terminal accuracy even after crediting real findings"
    elif gap > 0.03:
        verdict = "REVERSAL FLIPS — corrected accuracy favors memory (the seeded-only reversal was an oracle artifact)"
    else:
        verdict = "REVERSAL DISSOLVES into the noise band (|gap| ≤ 0.03) — no terminal-accuracy difference"
    print(f"\nVERDICT: {verdict}")
    print("(Note: rho-corrected precision credits real findings symmetrically; recall held at the "
          "seeded-oracle value. A full per-run recomputation — crediting each run's own adjudicated "
          "findings — is the exact version; this uniform-rho estimate matches the paper's §5 sensitivity.)")


if __name__ == "__main__":
    main()
