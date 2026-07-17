#!/usr/bin/env python3
"""M3 (round-2 MUST-FIX): mechanism comparison on the FAILURE mode, not just correct-convergence.

Reviewers (R1-3, R2): the mechanism-equivalence claim ("memory works, the mechanism doesn't")
is established only on correct-convergence (McNemar p=0.75). But the paper's own per-arm table
shows the engineered arms roughly DOUBLE the quiet failure — run-level false-convergence 0.072
(mem) vs 0.122 (ledger) / 0.139 (structured-memory) — never tested. And false-convergence should
be reported CONDITIONAL on settling, since nomem rarely settles at all.

This computes, per arm: settle rate, correct-convergence, false-convergence, and the honest
conditional P(wrong | settled) = FC / (CC + FC); then tests mem vs each engineered arm on the
per-artifact false-convergence count (exact McNemar on "artifact's majority regime is FC" is too
sparse, so we use a paired sign test on per-artifact FC-fraction differences over the 60 artifacts).

Reads runs/_scratch/B/metrics_recompute_all.json (V4-Pro main campaign).
"""
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "runs" / "_scratch" / "B" / "metrics_recompute_all.json"
OUTDIR = ROOT / "crossfamily_results"
CC, FC = "contractive-to-correct", "false-convergence"
ARMS = {
    "mem": {"mem", "mem-r2", "mem-r3"},
    "nomem": {"nomem", "nomem-r2", "nomem-r3"},
    "ledger": {"ledger", "ledger-r2", "ledger-r3"},
    "structured": {"structured-memory", "structured-memory-r2", "structured-memory-r3"},
}


def sign_test(diffs):
    """Two-sided exact sign test on nonzero paired differences (H0: median 0)."""
    pos = sum(d > 0 for d in diffs)
    neg = sum(d < 0 for d in diffs)
    n = pos + neg
    if n == 0:
        return 1.0, pos, neg
    k = min(pos, neg)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n)
    return p, pos, neg


def main():
    runs = json.loads(SRC.read_text())["runs"]
    by_arm = {a: [r for r in runs if r["config_id"] in cfgs] for a, cfgs in ARMS.items()}

    out = {}
    print("=" * 68)
    print("M3 — mechanism comparison on the FAILURE mode (P(wrong | settled))")
    print("=" * 68)
    print(f"\n{'arm':<12} {'n':>4} {'settle':>7} {'CC':>7} {'FC':>7} {'P(wrong|settled)':>17}")
    for a, rs in by_arm.items():
        n = len(rs)
        cc = sum(r["regime"] == CC for r in rs)
        fc = sum(r["regime"] == FC for r in rs)
        settled = cc + fc
        pw = fc / settled if settled else 0.0
        out[a] = {"n": n, "settle_rate": round(settled / n, 4), "cc_rate": round(cc / n, 4),
                  "fc_rate": round(fc / n, 4), "p_wrong_given_settled": round(pw, 4)}
        print(f"{a:<12} {n:>4} {settled/n:>7.3f} {cc/n:>7.3f} {fc/n:>7.3f} {pw:>17.3f}")

    # paired mem-vs-engineered on per-artifact false-convergence fraction (3 seeds each)
    def fc_frac_by_art(rs):
        by = defaultdict(list)
        for r in rs:
            by[r["artifact_id"]].append(r["regime"] == FC)
        return {art: sum(v) / len(v) for art, v in by.items()}

    mem_fc = fc_frac_by_art(by_arm["mem"])
    print(f"\nPaired test — engineered arm's false-convergence vs plain memory (per-artifact FC-fraction):")
    out["tests"] = {}
    for a in ("ledger", "structured", "nomem"):
        eng_fc = fc_frac_by_art(by_arm[a])
        arts = sorted(set(mem_fc) & set(eng_fc))
        diffs = [eng_fc[art] - mem_fc[art] for art in arts]   # >0 => engineered arm has MORE FC
        p, pos, neg = sign_test(diffs)
        mean_diff = sum(diffs) / len(diffs)
        out["tests"][f"{a}_vs_mem_fc"] = {"mean_fc_diff": round(mean_diff, 4),
                                          "artifacts_more_fc": pos, "artifacts_less_fc": neg,
                                          "sign_test_p": round(p, 5)}
        print(f"  {a:<12} mean FC diff {mean_diff:+.3f}  ({pos} arts more FC, {neg} fewer)  sign-test p={p:.4f}")

    OUTDIR.mkdir(exist_ok=True)
    (OUTDIR / "m3_false_convergence.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"\nwrote {OUTDIR/'m3_false_convergence.json'}")


if __name__ == "__main__":
    main()
