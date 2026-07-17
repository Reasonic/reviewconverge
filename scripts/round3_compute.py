#!/usr/bin/env python3
"""Round-3 SHOULD/MUST-FIX computations (offline, from existing metrics JSONs).

B (R3-5): cluster-bootstrap 95% CI for the defect-projection majority gap (+0.167) + discordant counts.
C (R3-S1): per-round recall / precision / F1 curves, mem vs nomem (does iteration beat single-shot?).
D (R3-4): full-re-judge per-trajectory regime agreement GPT-5.5 (n=360) vs V4-Pro + confusion counts.
"""
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
B = ROOT / "runs" / "_scratch" / "B"
OUT = ROOT / "crossfamily_results" / "round3_compute.json"
CC = "contractive-to-correct"
RNG = np.random.default_rng(20260715)
MEM = {"mem", "mem-r2", "mem-r3"}
NOM = {"nomem", "nomem-r2", "nomem-r3"}


def defset(re_):
    return frozenset(e for e in re_ if e.startswith("def:"))


def settled_dp(r):
    ds = [defset(x) for x in r["round_elements"]]
    return len(ds) >= 2 and ds[-1] == ds[-2]


def term_correct(r):
    return r["terminal_recall"] >= 0.80 and r["terminal_false_fraction"] <= 0.34


def regime_dp(r):
    if r["regime"] in (CC, "false-convergence"):
        return r["regime"]
    if settled_dp(r):
        return CC if term_correct(r) else "false-convergence"
    return r["regime"]


# ---------- B: defect-projection CI + counts ----------
def part_B(runs):
    mem = [r for r in runs if r["config_id"] in MEM]
    nom = [r for r in runs if r["config_id"] in NOM]

    def majcc(rows, fn):
        by = defaultdict(list)
        for r in rows:
            by[r["artifact_id"]].append(fn(r))
        return {a: (Counter(v).most_common(1)[0][0] == CC) for a, v in by.items()}

    mm, nn = majcc(mem, regime_dp), majcc(nom, regime_dp)
    arts = sorted(set(mm) & set(nn))
    b = sum(mm[a] and not nn[a] for a in arts)
    c = sum(nn[a] and not mm[a] for a in arts)
    obs = np.mean([mm[a] for a in arts]) - np.mean([nn[a] for a in arts])
    Bt = 20000
    boots = np.empty(Bt)
    for i in range(Bt):
        s = RNG.choice(arts, len(arts), True)
        boots[i] = np.mean([mm[a] for a in s]) - np.mean([nn[a] for a in s])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p = min(1.0, 2 * sum(math.comb(b + c, i) for i in range(min(b, c) + 1)) * 0.5 ** (b + c))
    return {"majority_gap": round(float(obs), 4), "discordant_b_mem_only": b, "c_nomem_only": c,
            "mcnemar_p_exact": round(p, 5), "cluster_bootstrap_ci95": [round(float(lo), 4), round(float(hi), 4)]}


# ---------- C: per-round P/R/F1 ----------
def part_C(runs):
    def curve(cfgs):
        # per-round accumulators
        R = defaultdict(list); P = defaultdict(list); F = defaultdict(list)
        for r in runs:
            if r["config_id"] not in cfgs:
                continue
            nd = r["n_defects"]
            for i, elems in enumerate(r["round_elements"]):
                d = sum(1 for e in elems if e.startswith("def:"))
                f = sum(1 for e in elems if e.startswith("false:"))
                rec = d / nd if nd else 0.0
                prec = d / (d + f) if (d + f) else 1.0
                f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
                R[i].append(rec); P[i].append(prec); F[i].append(f1)
        rounds = sorted(R)
        return {"recall": [round(float(np.mean(R[i])), 3) for i in rounds],
                "precision": [round(float(np.mean(P[i])), 3) for i in rounds],
                "f1": [round(float(np.mean(F[i])), 3) for i in rounds]}
    return {"mem": curve(MEM), "nomem": curve(NOM)}


# ---------- D: re-judge per-trajectory agreement ----------
def part_D():
    gpt = json.loads((B / "metrics_gpt_primary.json").read_text())["runs"]
    v4 = json.loads((B / "metrics_recompute_all.json").read_text())["runs"]
    key = lambda r: (r["artifact_id"], r["config_id"])
    gmap = {key(r): r["regime"] for r in gpt if r["config_id"] in MEM | NOM}
    vmap = {key(r): r["regime"] for r in v4 if r["config_id"] in MEM | NOM}
    common = sorted(set(gmap) & set(vmap))
    agree = sum(gmap[k] == vmap[k] for k in common)
    conf = Counter((vmap[k], gmap[k]) for k in common if vmap[k] != gmap[k])
    return {"n_common": len(common), "per_trajectory_agreement": round(agree / len(common), 4),
            "top_disagreements_v4pro_to_gpt55": [
                {"from": a, "to": b, "n": n} for (a, b), n in conf.most_common(6)]}


def main():
    runs = json.loads((B / "metrics_recompute_all.json").read_text())["runs"]
    out = {"B_defect_projection_ci": part_B(runs), "C_per_round_curves": part_C(runs),
           "D_rejudge_agreement": part_D()}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print("B (defect-projection):", json.dumps(out["B_defect_projection_ci"]))
    print("\nC per-round F1  mem  :", out["C_per_round_curves"]["mem"]["f1"])
    print("C per-round F1  nomem:", out["C_per_round_curves"]["nomem"]["f1"])
    print("C per-round recall mem   :", out["C_per_round_curves"]["mem"]["recall"])
    print("C per-round recall nomem :", out["C_per_round_curves"]["nomem"]["recall"])
    print("\nD re-judge per-trajectory agreement:", out["D_rejudge_agreement"]["per_trajectory_agreement"],
          f"({out['D_rejudge_agreement']['n_common']} traj)")
    for x in out["D_rejudge_agreement"]["top_disagreements_v4pro_to_gpt55"]:
        print(f"   {x['from']:<24} -> {x['to']:<24} {x['n']}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
