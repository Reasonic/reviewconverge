#!/usr/bin/env python3
"""Item-paired arm comparison + M4 diagnostics over ``compute_metrics`` JSON outputs.

Replaces the indefensible 3-point mean±SD reporting (Expert D, SHOULD-FIX 5): the
unit of analysis is the corpus artifacts paired across arms, with runs as a variance
component. Reports exact **McNemar** (regime flips) + **sign test** (continuous
metrics), plus round-0 balance, late-discovery normalized by opportunity, and
distinct-defects-found. Pool all replicate runs of an arm by passing every run's JSON.

Usage::

    python scripts/arm_stats.py --a ledger --b mem \\
        runs/_scratch/metrics_ledger_fix.json runs/_scratch/metrics_ledger-r2_fix.json ... \\
        runs/_scratch/metrics_mem_fix.json runs/_scratch/metrics_mem-r2_fix.json ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.metrics.armstats import compare_arms  # noqa: E402

CONT = ["mean_churn", "oscillation_degree", "stabilized_round",
        "terminal_precision", "terminal_false_fraction", "terminal_recall"]


def load_runs(paths):
    runs = []
    for p in paths:
        runs += json.load(open(p)).get("runs", [])
    return runs


def _sig(p):
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"


def main(argv):
    ap = argparse.ArgumentParser(description="Item-paired arm comparison + M4 diagnostics.")
    ap.add_argument("metrics", nargs="+", help="compute_metrics JSON files (all runs pooled)")
    ap.add_argument("--a", required=True, help="arm A config_id")
    ap.add_argument("--b", required=True, help="arm B config_id")
    args = ap.parse_args(argv[1:])

    runs = load_runs(args.metrics)
    A = [r for r in runs if r.get("config_id") == args.a]
    B = [r for r in runs if r.get("config_id") == args.b]
    if not A or not B:
        print(f"no runs for a={args.a!r} ({len(A)}) or b={args.b!r} ({len(B)}); present configs: "
              f"{sorted({r.get('config_id') for r in runs})}", file=sys.stderr)
        return 2

    res = compare_arms(A, B, CONT)
    print(f"\nARM COMPARISON   A={args.a}   vs   B={args.b}"
          f"   (item-paired over {res['n_artifacts']} artifacts; "
          f"A pooled {len(A)} runs / B pooled {len(B)} runs)\n")
    print(f"{'continuous metric':26s} {'mean A':>9} {'mean B':>9} {'A−B':>9}  {'+/−/=':>9}  p(sign)")
    for k, v in res["continuous"].items():
        print(f"{k:26s} {v['mean_a']:9.3f} {v['mean_b']:9.3f} {v['mean_diff']:+9.3f}  "
              f"{v['pos']:>2}/{v['neg']:>2}/{v['tie']:>2}  {v['p']:.4f} {_sig(v['p'])}")

    print("\nregime (per-artifact majority across replicates; exact McNemar):")
    for k, v in res["regime"].items():
        print(f"  {k:24s} rate A={v['rate_a']:.3f} B={v['rate_b']:.3f}  "
              f"discordant A-only={v['a_only']} B-only={v['b_only']}  p={v['p']:.4f} {_sig(v['p'])}")

    d = res["diagnostics"]
    r = d["round0_recall"]
    la, lb = d["late_discovery"]["a"], d["late_discovery"]["b"]
    da, db = d["distinct_defects"]["a"], d["distinct_defects"]["b"]
    print("\ndiagnostics (Expert D) — needs round_elements (recompute with the updated compute_metrics):")
    print(f"  round-0 recall balance : A={r['mean_a']:.3f} B={r['mean_b']:.3f}  "
          f"paired {r['pos']}/{r['neg']}/{r['tie']}  p={r['p']:.4f} {_sig(r['p'])}  "
          f"(want 'ns' — round 0 is the identical cold prompt)")
    print(f"  late-discovery / opp   : A={la['late_defects']}/{la['opportunity']}"
          f"={la['per_opportunity']:.3f}   B={lb['late_defects']}/{lb['opportunity']}={lb['per_opportunity']:.3f}")
    print(f"  distinct defects found : A={da['found']}/{da['total']}={da['rate']:.3f}   "
          f"B={db['found']}/{db['total']}={db['rate']:.3f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
