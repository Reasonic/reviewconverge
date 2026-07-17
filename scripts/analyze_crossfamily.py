#!/usr/bin/env python3
"""Analyze the FULL n=360 cross-family (GPT-5.5) re-judge of the mem/nomem campaign.

Reads runs/_scratch/B/metrics_gpt_primary.json (produced by compute_metrics once every
pair was judged by the standalone judger) and reports the memory->convergence effect under
the cross-family judge: run-level + per-artifact-majority CC-rate, exact McNemar, and the
side-by-side with the same-family V4-Pro primary. Writes crossfamily_results/analysis.json.
"""
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "runs" / "_scratch" / "B" / "metrics_gpt_primary.json"
OUTDIR = ROOT / "crossfamily_results"
CC = "contractive-to-correct"

# Same-family V4-Pro primary (paper §5 headline), for side-by-side.
V4PRO = {"run_mem": 0.728, "run_nomem": 0.544, "maj_mem": 0.833, "maj_nomem": 0.550,
         "mcnemar_b": 19, "mcnemar_c": 2, "mcnemar_p": 0.0002}


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n)


def main():
    runs = json.loads(SRC.read_text())["runs"]
    is_mem = lambda c: "mem" in c and "nomem" not in c
    mem = [r for r in runs if is_mem(r["config_id"])]
    nom = [r for r in runs if "nomem" in r["config_id"]]

    run_mem = sum(r["regime"] == CC for r in mem) / len(mem)
    run_nom = sum(r["regime"] == CC for r in nom) / len(nom)

    def majority(rs):
        by = defaultdict(list)
        for r in rs:
            by[r["artifact_id"]].append(r["regime"])
        return {a: Counter(v).most_common(1)[0][0] for a, v in by.items()}

    mm, nm = majority(mem), majority(nom)
    arts = sorted(set(mm) & set(nm))
    maj_mem = sum(mm[a] == CC for a in arts) / len(arts)
    maj_nom = sum(nm[a] == CC for a in arts) / len(arts)
    b = sum(mm[a] == CC and nm[a] != CC for a in arts)
    c = sum(nm[a] == CC and mm[a] != CC for a in arts)
    p = mcnemar_exact(b, c)

    out = {
        "judge": "openai:gpt-5.5 (cross-family)", "n_trajectories": len(runs),
        "n_mem_traj": len(mem), "n_nomem_traj": len(nom), "n_artifacts": len(arts),
        "run_level": {"mem_cc": round(run_mem, 4), "nomem_cc": round(run_nom, 4),
                      "gap": round(run_mem - run_nom, 4)},
        "per_artifact_majority": {
            "mem_cc": round(maj_mem, 4), "mem_cc_n": sum(mm[a] == CC for a in arts),
            "nomem_cc": round(maj_nom, 4), "nomem_cc_n": sum(nm[a] == CC for a in arts),
            "gap": round(maj_mem - maj_nom, 4),
            "mcnemar": {"b_mem_only": b, "c_nomem_only": c, "p_exact": round(p, 6)},
        },
        "v4pro_same_family_reference": V4PRO,
    }
    OUTDIR.mkdir(exist_ok=True)
    (OUTDIR / "analysis.json").write_text(json.dumps(out, indent=1) + "\n")

    print("=" * 64)
    print("FULL n=360 CROSS-FAMILY (GPT-5.5) RE-JUDGE  vs  V4-Pro same-family")
    print("=" * 64)
    print(f"trajectories: {len(runs)} (mem {len(mem)} / nomem {len(nom)}), artifacts {len(arts)}")
    print(f"\n                         GPT-5.5(cross)     V4-Pro(same)")
    print(f"run-level  CC  mem      {run_mem:.3f}            {V4PRO['run_mem']:.3f}")
    print(f"run-level  CC  nomem    {run_nom:.3f}            {V4PRO['run_nomem']:.3f}")
    print(f"           gap          +{run_mem-run_nom:.3f}           +{V4PRO['run_mem']-V4PRO['run_nomem']:.3f}")
    print(f"majority   CC  mem      {maj_mem:.3f}            {V4PRO['maj_mem']:.3f}")
    print(f"majority   CC  nomem    {maj_nom:.3f}            {V4PRO['maj_nomem']:.3f}")
    print(f"           gap          +{maj_mem-maj_nom:.3f}           +{V4PRO['maj_mem']-V4PRO['maj_nomem']:.3f}")
    print(f"McNemar (majority)      b={b} c={c} p={p:.5f}   b={V4PRO['mcnemar_b']} c={V4PRO['mcnemar_c']} p={V4PRO['mcnemar_p']}")
    print(f"\nwrote {OUTDIR/'analysis.json'}")


if __name__ == "__main__":
    main()
