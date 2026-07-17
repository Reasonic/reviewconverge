#!/usr/bin/env python3
"""M1 (round-2 MUST-FIX): re-derive convergence on the DEFECT-PROJECTION and test whether
the mem-vs-nomem correct-convergence gap survives.

Reviewer point (R2-1/R1-2): "settled" = last two canonical rounds identical, where the
canonical set includes cross-round-matched FALSE-finding clusters (`false:k`). Memory
re-emits near-identical wording, so its false clusters map stably while no-memory redraws
fresh paraphrases that the finding-vs-finding matcher clusters differently each round —
so nomem looks "unsettled" partly for a phrasing reason, not a defect reason. This is the
measurement-channel confound sitting *inside* the correct-convergence headline.

Fix: define "settled" on the DEFECT PROJECTION only — two rounds are settled iff they claim
the same SET of seeded defects (`def:<id>` elements), matched by the recall-type finding->defect
matcher (arm-invariant). Terminal correctness (recall>=0.80 AND false-fraction<=0.34) is
UNCHANGED — only the settle criterion moves. If the gap survives, the channel confound is
substantially controlled with NO new data/human labels; if it shrinks, we report by how much.

Reads runs/_scratch/B/metrics_recompute_all.json (V4-Pro-judged main campaign, 840 traj).
"""
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "runs" / "_scratch" / "B" / "metrics_recompute_all.json"
OUTDIR = ROOT / "crossfamily_results"  # reuse the tracked results dir
CC = "contractive-to-correct"
CORRECT_RECALL, CORRECT_MAX_FALSE = 0.80, 0.34
MEM = {"mem", "mem-r2", "mem-r3"}
NOMEM = {"nomem", "nomem-r2", "nomem-r3"}


def defect_set(round_elems):
    return frozenset(e for e in round_elems if e.startswith("def:"))


def settled_defproj(r):
    ds = [defect_set(re) for re in r["round_elements"]]
    return len(ds) >= 2 and ds[-1] == ds[-2]


def terminal_correct(r):
    return r["terminal_recall"] >= CORRECT_RECALL and r["terminal_false_fraction"] <= CORRECT_MAX_FALSE


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n)


def regime_defproj(r):
    """Full regime under the defect-projection settle. Monotone: full-set-converged implies
    defect-converged, so an orig-CC/false-conv run keeps its (converged) label; only orig
    churn/divergent runs can flip to CC/false-conv if their DEFECT set is now settled."""
    if r["regime"] in (CC, "false-convergence"):
        return r["regime"]                      # was converged (full set) -> still converged
    if settled_defproj(r):                       # now settles on defects
        return CC if terminal_correct(r) else "false-convergence"
    return r["regime"]                           # still oscillatory-churn / divergent


def rates(rows, regime_fn):
    """run-level CC rate + per-artifact most-common-regime (paper's majority estimand)."""
    run = sum(regime_fn(r) == CC for r in rows) / len(rows)
    by = defaultdict(list)
    for r in rows:
        by[r["artifact_id"]].append(regime_fn(r))
    maj = {a: (Counter(v).most_common(1)[0][0] == CC) for a, v in by.items()}
    return run, maj


def main():
    runs = json.loads(SRC.read_text())["runs"]
    mem = [r for r in runs if r["config_id"] in MEM]
    nom = [r for r in runs if r["config_id"] in NOMEM]
    assert len(mem) == 180 and len(nom) == 180, (len(mem), len(nom))

    regime_orig = lambda r: r["regime"]

    out = {"n_mem": len(mem), "n_nomem": len(nom)}
    for name, regime_fn in [("original_full_set_settle", regime_orig),
                            ("defect_projection_settle", regime_defproj)]:
        m_run, m_maj = rates(mem, regime_fn)
        n_run, n_maj = rates(nom, regime_fn)
        arts = sorted(set(m_maj) & set(n_maj))
        b = sum(m_maj[a] and not n_maj[a] for a in arts)   # mem-only CC
        c = sum(n_maj[a] and not m_maj[a] for a in arts)   # nomem-only CC
        p = mcnemar_exact(b, c)
        mm = sum(m_maj[a] for a in arts) / len(arts)
        nn = sum(n_maj[a] for a in arts) / len(arts)
        out[name] = {
            "run_level": {"mem": round(m_run, 4), "nomem": round(n_run, 4), "gap": round(m_run - n_run, 4)},
            "majority": {"mem": round(mm, 4), "nomem": round(nn, 4), "gap": round(mm - nn, 4),
                         "mcnemar": {"b_mem_only": b, "c_nomem_only": c, "p_exact": round(p, 6)}},
        }

    # where do nomem trajectories move under the looser settle? (the confound's footprint)
    moved = Counter()
    for r in nom:
        o, d = r["regime"], regime_defproj(r)
        if o != CC and d == CC:
            moved["nomem: churn/div -> CC (defect-set was stable; false-wording churned)"] += 1
        elif o not in (CC, "false-convergence") and d == "false-convergence":
            moved["nomem: churn/div -> false-conv (settled on defects but too many false)"] += 1
    out["nomem_reclassification"] = dict(moved)
    OUTDIR.mkdir(exist_ok=True)
    (OUTDIR / "m1_defect_projection.json").write_text(json.dumps(out, indent=1) + "\n")

    print("=" * 70)
    print("M1 — does the mem-vs-nomem correct-convergence gap survive a PHRASING-INVARIANT")
    print("     (defect-projection) settle criterion?  [V4-Pro main campaign, 60 artifacts x3]")
    print("=" * 70)
    for name in ("original_full_set_settle", "defect_projection_settle"):
        s = out[name]
        print(f"\n[{name}]")
        print(f"  run-level  CC:  mem {s['run_level']['mem']:.3f}  nomem {s['run_level']['nomem']:.3f}  gap +{s['run_level']['gap']:.3f}")
        mj = s["majority"]
        print(f"  majority   CC:  mem {mj['mem']:.3f}  nomem {mj['nomem']:.3f}  gap +{mj['gap']:.3f}  "
              f"(McNemar b={mj['mcnemar']['b_mem_only']} c={mj['mcnemar']['c_nomem_only']} p={mj['mcnemar']['p_exact']})")
    print(f"\nnomem reclassification under defect-projection settle:")
    for k, v in out["nomem_reclassification"].items():
        print(f"  {v:3d}/180  {k}")
    print(f"\nwrote {OUTDIR/'m1_defect_projection.json'}")


if __name__ == "__main__":
    main()
