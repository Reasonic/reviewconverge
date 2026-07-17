#!/usr/bin/env python3
"""Analyze the realistic-scale probe campaign (mem vs nomem x 3 seeds, V4-Pro judge).

Answers the two probe questions (R3-M1 scale, R3-M2 contamination):
  1. Does the memory->convergence effect REPLICATE on longer, uncontaminated artifacts?
     -> CC-rate (contractive-to-correct) mem vs nomem, both estimands, exact McNemar.
  2. Does terminal RECALL drop off the ceiling on realistic-scale artifacts?
     -> terminal_recall distribution mem/nomem; # artifacts below ceiling.

Reads runs/_scratch/probe_campaign/metrics_{mem,nomem}_s{1,2,3}.json and writes
probe_analysis.json + a human summary to stdout. Pure stdlib (exact binomial McNemar).
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "runs" / "_scratch" / "probe_campaign"
CC = "contractive-to-correct"
SEEDS = (1, 2, 3)


def load():
    """rows: list of per-trajectory dicts tagged with config in {mem,nomem}."""
    rows = []
    for cfg in ("mem", "nomem"):
        for s in SEEDS:
            f = ROOT / f"metrics_{cfg}_s{s}.json"
            if not f.exists():
                raise SystemExit(f"missing {f} - run score_probe_campaign.sh first")
            d = json.loads(f.read_text())
            for r in d["runs"]:
                r["_cfg"] = cfg
                r["_seed"] = s
                rows.append(r)
    return rows


def majority(labels):
    """Most common label; deterministic tie-break by first appearance (armstats)."""
    return Counter(labels).most_common(1)[0][0]


def mcnemar_exact(b, c):
    """Two-sided exact McNemar (binomial, p=.5). b, c = discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2 * tail)


def main():
    rows = load()
    arts = sorted({r["artifact_id"] for r in rows})

    # ---- per-trajectory (run-level estimand) ----
    def cc_rate(cfg):
        rs = [r for r in rows if r["_cfg"] == cfg]
        return sum(r["regime"] == CC for r in rs) / len(rs), len(rs)
    mem_run, n_mem = cc_rate("mem")
    nomem_run, n_nomem = cc_rate("nomem")

    # ---- per-artifact-majority estimand ----
    maj = {}  # (cfg, art) -> majority regime
    recall = defaultdict(dict)  # (cfg) -> art -> mean terminal recall
    conv = defaultdict(dict)
    for cfg in ("mem", "nomem"):
        for art in arts:
            sub = [r for r in rows if r["_cfg"] == cfg and r["artifact_id"] == art]
            maj[(cfg, art)] = majority([r["regime"] for r in sub])
            recall[cfg][art] = sum(r["terminal_recall"] for r in sub) / len(sub)
            conv[cfg][art] = sum(bool(r["converged"]) for r in sub) / len(sub)

    mem_cc = [art for art in arts if maj[("mem", art)] == CC]
    nomem_cc = [art for art in arts if maj[("nomem", art)] == CC]
    mem_maj_rate = len(mem_cc) / len(arts)
    nomem_maj_rate = len(nomem_cc) / len(arts)

    # McNemar on the per-artifact CC indicator
    b = sum(maj[("mem", a)] == CC and maj[("nomem", a)] != CC for a in arts)  # mem-only CC
    c = sum(maj[("nomem", a)] == CC and maj[("mem", a)] != CC for a in arts)  # nomem-only CC
    p_mcnemar = mcnemar_exact(b, c)

    # ---- recall distribution ----
    def rstats(cfg):
        vals = [r["terminal_recall"] for r in rows if r["_cfg"] == cfg]
        art_means = [recall[cfg][a] for a in arts]
        return {
            "traj_mean": round(sum(vals) / len(vals), 4),
            "traj_min": round(min(vals), 4),
            "artifacts_below_ceiling": sum(m < 0.999 for m in art_means),
            "artifacts_at_ceiling": sum(m >= 0.999 for m in art_means),
            "per_artifact_mean_recall": {a: round(recall[cfg][a], 3) for a in arts},
        }
    rec_mem, rec_nomem = rstats("mem"), rstats("nomem")

    out = {
        "n_artifacts": len(arts),
        "seeds": list(SEEDS),
        "run_level": {
            "mem_cc_rate": round(mem_run, 4), "n_mem_traj": n_mem,
            "nomem_cc_rate": round(nomem_run, 4), "n_nomem_traj": n_nomem,
        },
        "per_artifact_majority": {
            "mem_cc_rate": round(mem_maj_rate, 4), "mem_cc_artifacts": mem_cc,
            "nomem_cc_rate": round(nomem_maj_rate, 4), "nomem_cc_artifacts": nomem_cc,
            "mcnemar": {"b_mem_only_cc": b, "c_nomem_only_cc": c, "p_exact": round(p_mcnemar, 5)},
        },
        "recall": {"mem": rec_mem, "nomem": rec_nomem},
        "per_artifact_table": [
            {"artifact": a,
             "mem_regime": maj[("mem", a)], "nomem_regime": maj[("nomem", a)],
             "mem_recall": round(recall["mem"][a], 3), "nomem_recall": round(recall["nomem"][a], 3),
             "mem_conv": round(conv["mem"][a], 2), "nomem_conv": round(conv["nomem"][a], 2)}
            for a in arts
        ],
    }
    (ROOT / "probe_analysis.json").write_text(json.dumps(out, indent=1) + "\n")

    # ---- human summary ----
    print("=" * 66)
    print("REALISTIC-SCALE PROBE — mem vs nomem (V4-Pro judge), 10 artifacts x 3 seeds")
    print("=" * 66)
    print(f"\nRQ (replication): does memory->convergence hold on longer/uncontaminated code?")
    print(f"  run-level      CC-rate:  mem {mem_run:.2f} ({n_mem} traj)  vs  nomem {nomem_run:.2f} ({n_nomem} traj)")
    print(f"  per-artifact   CC-rate:  mem {mem_maj_rate:.2f} ({len(mem_cc)}/10)  vs  nomem {nomem_maj_rate:.2f} ({len(nomem_cc)}/10)")
    print(f"  McNemar (per-artifact CC): mem-only={b}, nomem-only={c}, exact p={p_mcnemar:.4f}")
    print(f"\nRQ (recall off ceiling?): terminal recall on realistic-scale artifacts")
    print(f"  mem   : traj-mean {rec_mem['traj_mean']:.2f}, min {rec_mem['traj_min']:.2f}, "
          f"{rec_mem['artifacts_below_ceiling']}/10 artifacts below ceiling")
    print(f"  nomem : traj-mean {rec_nomem['traj_mean']:.2f}, min {rec_nomem['traj_min']:.2f}, "
          f"{rec_nomem['artifacts_below_ceiling']}/10 artifacts below ceiling")
    print(f"\nper-artifact (majority regime | mean terminal recall):")
    print(f"  {'artifact':<12} {'mem-regime':<24} {'nomem-regime':<24} {'memR':>5} {'nomR':>5}")
    for t in out["per_artifact_table"]:
        print(f"  {t['artifact']:<12} {t['mem_regime']:<24} {t['nomem_regime']:<24} "
              f"{t['mem_recall']:>5.2f} {t['nomem_recall']:>5.2f}")
    print(f"\nwrote {ROOT/'probe_analysis.json'}")


if __name__ == "__main__":
    main()
