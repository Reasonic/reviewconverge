#!/usr/bin/env python3
"""Round-2 SHOULD-FIX statistics supplement (S8, S9, S10) on the V4-Pro main campaign.

S8 (R3): the continuous-metric rows use the *sign* test (discards magnitude) and one row
   pairs a mean-difference CI (crosses 0) with a "significant" sign p. Report the
   test-matched Hodges-Lehmann median difference + 95% CI and the (more powerful) Wilcoxon
   signed-rank p for the key continuous comparisons.
S9 (R3): the run-level +0.184 gets no valid test (180 runs are clustered in 60 artifacts).
   Report a cluster-bootstrap CI + p for the run-level mem-vs-nomem CC difference.
S10 (R3): the equivalence claims are asserted via 95%-CI containment; report actual TOST
   p-values (bootstrap) for the mechanism nulls at +/-0.15 and +/-0.10, and for recall.

Reads runs/_scratch/B/metrics_recompute_all.json.
"""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "runs" / "_scratch" / "B" / "metrics_recompute_all.json"
OUT = ROOT / "crossfamily_results" / "s_stats_supplement.json"
CC = "contractive-to-correct"
RNG = np.random.default_rng(20260714)
ARMS = {"mem": {"mem", "mem-r2", "mem-r3"}, "nomem": {"nomem", "nomem-r2", "nomem-r3"},
        "ledger": {"ledger", "ledger-r2", "ledger-r3"},
        "structured": {"structured-memory", "structured-memory-r2", "structured-memory-r3"}}


def load():
    runs = json.loads(SRC.read_text())["runs"]
    return {a: [r for r in runs if r["config_id"] in c] for a, c in ARMS.items()}


def per_artifact_mean(rows, key):
    by = defaultdict(list)
    for r in rows:
        by[r["artifact_id"]].append(r[key])
    return {a: float(np.mean(v)) for a, v in by.items()}


def per_artifact_majcc(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["artifact_id"]].append(r["regime"])
    from collections import Counter
    return {a: (Counter(v).most_common(1)[0][0] == CC) for a, v in by.items()}


def hodges_lehmann(diffs):
    """HL estimator (median of Walsh averages) + distribution-free 95% CI via Walsh order stats."""
    d = np.sort(np.asarray(diffs, float))
    walsh = np.array([(d[i] + d[j]) / 2 for i in range(len(d)) for j in range(i, len(d))])
    walsh.sort()
    est = float(np.median(walsh))
    # Wilcoxon 95% CI: the k-th and (M+1-k)-th Walsh averages (normal approx to critical rank)
    n = len(d); M = len(walsh)
    se = np.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    k = int(round(M / 2 - 1.959964 * se))
    k = max(1, min(k, M // 2))
    return est, float(walsh[k - 1]), float(walsh[M - k])


def s8(by):
    arts = sorted(set(a for a in per_artifact_mean(by["mem"], "mean_churn")))
    out = {}
    pairs = [("mem", "nomem"), ("ledger", "mem"), ("structured", "mem")]
    metrics = [("mean_churn", "churn"), ("oscillation_degree", "oscillation"),
               ("stabilized_round", "stabilized_round"), ("terminal_precision", "precision"),
               ("terminal_recall", "recall")]
    for a1, a2 in pairs:
        m1 = per_artifact_mean(by[a1], None) if False else None
        for key, name in metrics:
            d1 = per_artifact_mean(by[a1], key); d2 = per_artifact_mean(by[a2], key)
            diffs = np.array([d1[a] - d2[a] for a in arts])
            if np.allclose(diffs, 0):
                out[f"{a1}_vs_{a2}:{name}"] = {"note": "all zero"}
                continue
            try:
                w = stats.wilcoxon(diffs, zero_method="wilcox", correction=False,
                                   alternative="two-sided", mode="auto")
                wp = float(w.pvalue)
            except Exception:
                wp = None
            hl, lo, hi = hodges_lehmann(diffs[diffs != 0]) if np.any(diffs != 0) else (0, 0, 0)
            out[f"{a1}_vs_{a2}:{name}"] = {"wilcoxon_p": None if wp is None else round(wp, 5),
                                          "hodges_lehmann": round(hl, 4),
                                          "hl_ci95": [round(lo, 4), round(hi, 4)],
                                          "mean_diff": round(float(diffs.mean()), 4)}
    return out


def s9(by, B=20000):
    mem_by = defaultdict(list); nom_by = defaultdict(list)
    for r in by["mem"]:
        mem_by[r["artifact_id"]].append(r["regime"] == CC)
    for r in by["nomem"]:
        nom_by[r["artifact_id"]].append(r["regime"] == CC)
    arts = sorted(set(mem_by) & set(nom_by))
    obs = np.mean([x for a in arts for x in mem_by[a]]) - np.mean([x for a in arts for x in nom_by[a]])
    boots = np.empty(B)
    for b in range(B):
        samp = RNG.choice(arts, size=len(arts), replace=True)
        m = np.mean([x for a in samp for x in mem_by[a]])
        n = np.mean([x for a in samp for x in nom_by[a]])
        boots[b] = m - n
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    return {"run_level_cc_diff_mem_minus_nomem": round(float(obs), 4),
            "cluster_bootstrap_ci95": [round(float(lo), 4), round(float(hi), 4)],
            "cluster_bootstrap_p": round(float(min(1.0, p)), 5), "B": B}


def s10(by, margins=(0.15, 0.10), B=20000):
    """Bootstrap TOST on the per-artifact-majority CC difference for the mechanism nulls + recall."""
    def maj_diff_boot(a1, a2):
        c1 = per_artifact_majcc(by[a1]); c2 = per_artifact_majcc(by[a2])
        arts = sorted(set(c1) & set(c2))
        obs = np.mean([c1[a] for a in arts]) - np.mean([c2[a] for a in arts])
        boots = np.empty(B)
        for b in range(B):
            s = RNG.choice(arts, len(arts), True)
            boots[b] = np.mean([c1[a] for a in s]) - np.mean([c2[a] for a in s])
        return obs, boots
    out = {}
    for a1, a2 in [("ledger", "mem"), ("structured", "mem")]:
        obs, boots = maj_diff_boot(a1, a2)
        lo90, hi90 = np.percentile(boots, [5, 95])
        row = {"obs_diff": round(float(obs), 4), "ci90": [round(float(lo90), 4), round(float(hi90), 4)]}
        for d in margins:
            p_up = (boots >= d).mean(); p_lo = (boots <= -d).mean()
            row[f"tost_p_margin_{d}"] = round(float(max(p_up, p_lo)), 5)
            row[f"equivalent_at_{d}"] = bool(-d < lo90 and hi90 < d)
        out[f"{a1}_vs_mem"] = row
    # recall equivalence (mem vs nomem)
    rm = per_artifact_mean(by["mem"], "terminal_recall"); rn = per_artifact_mean(by["nomem"], "terminal_recall")
    arts = sorted(set(rm) & set(rn))
    obs = np.mean([rm[a] - rn[a] for a in arts])
    boots = np.array([np.mean([rm[a] - rn[a] for a in RNG.choice(arts, len(arts), True)]) for _ in range(B)])
    lo90, hi90 = np.percentile(boots, [5, 95])
    out["recall_mem_vs_nomem"] = {"obs_diff": round(float(obs), 4), "ci90": [round(float(lo90), 4), round(float(hi90), 4)],
                                  "tost_p_margin_0.05": round(float(max((boots >= 0.05).mean(), (boots <= -0.05).mean())), 5),
                                  "equivalent_at_0.05": bool(-0.05 < lo90 and hi90 < 0.05)}
    return out


def main():
    by = load()
    result = {"S8_wilcoxon_hodges_lehmann": s8(by), "S9_cluster_bootstrap_runlevel": s9(by),
              "S10_tost": s10(by)}
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    import pprint
    print("=== S8 Wilcoxon signed-rank + Hodges-Lehmann (key rows) ===")
    for k in ("mem_vs_nomem:churn", "mem_vs_nomem:oscillation", "mem_vs_nomem:stabilized_round",
              "mem_vs_nomem:precision", "mem_vs_nomem:recall", "ledger_vs_mem:stabilized_round",
              "structured_vs_mem:stabilized_round"):
        print(f"  {k:<34} {result['S8_wilcoxon_hodges_lehmann'].get(k)}")
    print("\n=== S9 cluster-bootstrap run-level mem-vs-nomem CC ===")
    print(" ", result["S9_cluster_bootstrap_runlevel"])
    print("\n=== S10 TOST (bootstrap) ===")
    for k, v in result["S10_tost"].items():
        print(f"  {k:<22} {v}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
