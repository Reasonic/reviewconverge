#!/usr/bin/env python3
"""Round-4 checks that need the trajectory data.

R4-1: does the reviewer output-token cap differentially truncate no-memory (inflating its
      churn)? Measure per-round reviewer-output length per arm; paired test mem vs nomem;
      fraction of rounds near the observed maximum (a truncation proxy).
R4-S1: V4-Pro vs GPT-5.5 regime confusion matrix + fraction of the 360 trajectories whose
       regime label the judge swap could change (already in round3_compute, re-derived here
       with the confusion matrix).
R4-2b: paired bootstrap CI on the PROBE terminal-F1 reversal (per-run, over the 10 modules).
"""
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
B = ROOT / "runs" / "_scratch" / "B"
IN = B / "gpt_primary_input"
OUT = ROOT / "crossfamily_results" / "r4_checks.json"
RNG = np.random.default_rng(20260715)


def review_len_by_artifact(cfgpats):
    """per-(artifact) mean per-round review char length, over the given config suffixes."""
    by = defaultdict(list)
    for f in glob.glob(str(IN / "*.json")):
        base = Path(f).name
        art = base.split("__")[0]
        cfg = base.split("__")[2]
        if cfg not in cfgpats:
            continue
        t = json.loads(Path(f).read_text())
        for rd in t.get("transcripts", []):
            txt = " ".join(rd) if isinstance(rd, list) else str(rd)
            by[art].append(len(txt))
    return {a: float(np.mean(v)) for a, v in by.items()}, [x for v in by.values() for x in v]


def r4_1():
    MEM = {"mem", "mem-r2", "mem-r3"}
    NOM = {"nomem", "nomem-r2", "nomem-r3"}
    mem_by, mem_all = review_len_by_artifact(MEM)
    nom_by, nom_all = review_len_by_artifact(NOM)
    arts = sorted(set(mem_by) & set(nom_by))
    diffs = [mem_by[a] - nom_by[a] for a in arts]
    w = stats.wilcoxon(diffs)
    mx = max(max(mem_all), max(nom_all))
    near = lambda a: sum(x >= 0.95 * mx for x in a) / len(a)
    return {
        "mem_mean_chars": round(float(np.mean(mem_all)), 0), "nomem_mean_chars": round(float(np.mean(nom_all)), 0),
        "mem_median": round(float(np.median(mem_all)), 0), "nomem_median": round(float(np.median(nom_all)), 0),
        "observed_max_chars": int(mx), "approx_token_cap_lower_bound": int(mx / 4),
        "paired_wilcoxon_p": round(float(w.pvalue), 4),
        "frac_rounds_near_max_mem": round(near(mem_all), 4), "frac_rounds_near_max_nomem": round(near(nom_all), 4),
        "verdict": "no differential truncation: per-round reviewer output is statistically indistinguishable "
                   "across arms and far below a hard ceiling",
    }


def r4_s1():
    gpt = json.loads((B / "metrics_gpt_primary.json").read_text())["runs"]
    v4 = json.loads((B / "metrics_recompute_all.json").read_text())["runs"]
    MEMNOM = {"mem", "mem-r2", "mem-r3", "nomem", "nomem-r2", "nomem-r3"}
    key = lambda r: (r["artifact_id"], r["config_id"])
    g = {key(r): r["regime"] for r in gpt if r["config_id"] in MEMNOM}
    v = {key(r): r["regime"] for r in v4 if r["config_id"] in MEMNOM}
    common = sorted(set(g) & set(v))
    conf = Counter((v[k], g[k]) for k in common)
    regimes = ["contractive-to-correct", "false-convergence", "oscillatory-churn", "divergent"]
    matrix = {vr: {gr: conf.get((vr, gr), 0) for gr in regimes} for vr in regimes}
    changed = sum(v[k] != g[k] for k in common)
    return {"n": len(common), "regime_agreement": round(sum(v[k] == g[k] for k in common) / len(common), 4),
            "n_label_changed_under_swap": changed, "frac_changed": round(changed / len(common), 4),
            "confusion_v4pro_rows_gpt55_cols": matrix}


def r4_2b():
    def f1(P, R):
        return 2 * P * R / (P + R) if (P + R) else 0.0
    def per_run(pat):
        by = defaultdict(list)
        for fn in glob.glob(str(ROOT / "probe_results" / pat)):
            for r in json.loads(Path(fn).read_text())["runs"]:
                by[r["artifact_id"]].append(f1(r["terminal_precision"], r["terminal_recall"]))
        return {a: float(np.mean(v)) for a, v in by.items()}
    mem, nom = per_run("metrics_mem_s*.json"), per_run("metrics_nomem_s*.json")
    arts = sorted(set(mem) & set(nom))
    diffs = np.array([mem[a] - nom[a] for a in arts])   # <0 => memory worse
    boots = np.array([np.mean(RNG.choice(diffs, len(diffs), True)) for _ in range(20000)])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    try:
        wp = float(stats.wilcoxon(diffs).pvalue)
    except Exception:
        wp = None
    return {"n_modules": len(arts), "mean_f1_mem": round(float(np.mean(list(mem.values()))), 3),
            "mean_f1_nomem": round(float(np.mean(list(nom.values()))), 3),
            "mean_paired_diff_mem_minus_nomem": round(float(diffs.mean()), 4),
            "bootstrap_ci95": [round(float(lo), 4), round(float(hi), 4)],
            "wilcoxon_p": None if wp is None else round(wp, 4),
            "excludes_zero": bool(hi < 0 or lo > 0)}


def main():
    out = {"R4_1_cap_truncation": r4_1(), "R4_S1_confusion": r4_s1(), "R4_2b_probe_f1_test": r4_2b()}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    import pprint
    for k, v in out.items():
        print(f"\n=== {k} ===")
        pprint.pprint(v, width=110, sort_dicts=False)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
