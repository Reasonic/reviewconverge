#!/usr/bin/env python3
"""Post-simulation fix-pass computations (all offline, from metrics_recompute_all.json).

R5-1: per-round F1 round-1-vs-round-6 paired test + TOST per arm (was asserted "flat" untested).
R5-2: terminal canonical set-size distribution vs the corpus's 3-4-defect regularity.
R5-3: stop-at-first-stability rule — early-stop rate + P(wrong | early stop) per arm.
R5-4: memorization-suspect item exclusion (mem_ratio >= 0.5, n=14) headline sensitivity.
R5-5: merge the gray-policy full-dynamics re-derivation (runs/_scratch/B/gray_dynamics.json,
      produced by runs/_scratch/B/regray_dynamics.py on the warm cache).
"""
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
B = ROOT / "runs" / "_scratch" / "B"
OUT = ROOT / "crossfamily_results" / "r5_checks.json"
RNG = np.random.default_rng(20260716)

MEM = {"mem", "mem-r2", "mem-r3"}
NOM = {"nomem", "nomem-r2", "nomem-r3"}
LED = {"ledger", "ledger-r2", "ledger-r3"}
STR = {"structured-memory", "structured-memory-r2", "structured-memory-r3"}
CC = "contractive-to-correct"

runs = json.loads((B / "metrics_recompute_all.json").read_text())["runs"]


def round_f1(elems, nd):
    d = sum(1 for e in elems if e.startswith("def:"))
    f = sum(1 for e in elems if e.startswith("false:"))
    rec = d / nd if nd else 0.0
    prec = d / (d + f) if (d + f) else 1.0
    return 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0


def r5_1():
    out = {}
    for name, cfgs in (("mem", MEM), ("nomem", NOM)):
        by1, by6 = defaultdict(list), defaultdict(list)
        for r in runs:
            if r["config_id"] not in cfgs:
                continue
            by1[r["artifact_id"]].append(round_f1(r["round_elements"][0], r["n_defects"]))
            by6[r["artifact_id"]].append(round_f1(r["round_elements"][-1], r["n_defects"]))
        arts = sorted(by1)
        d = np.array([np.mean(by6[a]) - np.mean(by1[a]) for a in arts])
        w = stats.wilcoxon(d)
        boots = np.array([np.mean(RNG.choice(d, len(d), True)) for _ in range(20000)])
        lo, hi = np.percentile(boots, [2.5, 97.5])
        lo90, hi90 = np.percentile(boots, [5, 95])
        m = 0.05
        ptost = max(float((boots >= m).mean()), float((boots <= -m).mean()))
        out[name] = {"mean_diff_r6_minus_r1": round(float(d.mean()), 4),
                     "wilcoxon_p": round(float(w.pvalue), 4),
                     "ci95": [round(float(lo), 4), round(float(hi), 4)],
                     "ci90": [round(float(lo90), 4), round(float(hi90), 4)],
                     "tost_pm005_p": round(ptost, 4)}
    return out


def r5_2():
    out = {}
    for name, cfgs in (("mem", MEM), ("nomem", NOM), ("ledger", LED), ("structured-memory", STR)):
        sizes = np.array([len(r["round_elements"][-1]) for r in runs if r["config_id"] in cfgs])
        out[name] = {"mean": round(float(sizes.mean()), 2), "sd": round(float(sizes.std()), 2),
                     "frac_in_3_4": round(float(np.mean((sizes >= 3) & (sizes <= 4))), 3),
                     "dist": {int(k): int(v) for k, v in zip(*np.unique(sizes, return_counts=True))}}
    return out


def r5_3():
    def first_stable(elems_rounds, nd):
        for i in range(len(elems_rounds) - 1):
            if set(elems_rounds[i]) == set(elems_rounds[i + 1]):
                term = elems_rounds[i + 1]
                d = sum(1 for e in term if e.startswith("def:"))
                f = sum(1 for e in term if e.startswith("false:"))
                rec = d / nd if nd else 0.0
                ff = f / (d + f) if (d + f) else 0.0
                return True, (rec >= 0.80 and ff <= 0.34)
        return False, False

    out = {}
    tot_stop = tot_wrong = 0
    for name, cfgs in (("mem", MEM), ("nomem", NOM), ("ledger", LED), ("structured-memory", STR)):
        st = wr = n = 0
        for r in runs:
            if r["config_id"] not in cfgs:
                continue
            n += 1
            s, ok = first_stable(r["round_elements"], r["n_defects"])
            if s:
                st += 1
                wr += (not ok)
        tot_stop += st
        tot_wrong += wr
        out[name] = {"early_stop_rate": round(st / n, 3), "p_wrong_given_stop": round(wr / st, 3),
                     "stopped": st, "wrong": wr, "n": n}
    out["pooled_p_wrong_given_stop"] = round(tot_wrong / tot_stop, 4)
    return out


def r5_4():
    cp = json.loads((B / "contamination_probe.json").read_text())["items"]
    hi = {it["id"] for it in cp if it["mem_ratio"] >= 0.5}

    def maj(cfgs, excl):
        by = defaultdict(list)
        for r in runs:
            if r["config_id"] in cfgs and r["artifact_id"] not in excl:
                by[r["artifact_id"]].append(r["regime"])
        return {a: Counter(v).most_common(1)[0][0] == CC for a, v in by.items()}

    def mcn(excl):
        m, n = maj(MEM, excl), maj(NOM, excl)
        arts = sorted(set(m) & set(n))
        b = sum(m[a] and not n[a] for a in arts)
        c = sum(n[a] and not m[a] for a in arts)
        p = min(1.0, 2 * sum(math.comb(b + c, i) for i in range(min(b, c) + 1)) * 0.5 ** (b + c))
        return {"n_artifacts": len(arts), "mem_cc": round(sum(m[a] for a in arts) / len(arts), 3),
                "nomem_cc": round(sum(n[a] for a in arts) / len(arts), 3), "b": b, "c": c,
                "mcnemar_p": round(p, 5)}

    return {"n_excluded": len(hi), "excluded": sorted(hi), "full": mcn(set()), "excluded_result": mcn(hi)}


def main():
    out = {"R5_1_round1_vs_round6_f1": r5_1(), "R5_2_terminal_set_sizes": r5_2(),
           "R5_3_stop_at_first_stability": r5_3(), "R5_4_memorization_exclusion": r5_4()}
    gd = B / "gray_dynamics.json"
    if gd.exists():
        out["R5_5_gray_policy_full_dynamics"] = json.loads(gd.read_text())
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "R5_5_gray_policy_full_dynamics"}, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
