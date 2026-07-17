"""Item-paired statistics + M4 diagnostics for arm comparisons (Expert D, SHOULD-FIX 5).

The defensible unit of analysis is the **60 corpus artifacts, paired across arms**,
with run-to-run variation folded in as a variance component — not a 3-point mean±SD
over run-level rates. This module provides dependency-free *exact* nonparametric
tests (McNemar for regime flips, the sign test for continuous metrics) plus the
offline diagnostics Expert D asked for (round-0 balance, late-discovery normalized by
opportunity, distinct defects found), all computed from the per-round canonical
element sets (``round_elements``) that ``compute_metrics`` emits. No SciPy needed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from math import comb
from statistics import mean

TOL = 1e-9

# -- exact nonparametric tests (p = 0.5 null) -----------------------------------
def _binom_two_sided(k: int, n: int) -> float:
    """Two-sided exact binomial p-value for k of n under p=0.5 (sum of outcomes no
    more likely than the observed)."""
    if n == 0:
        return 1.0
    probs = [comb(n, i) * 0.5 ** n for i in range(n + 1)]
    obs = probs[k]
    return min(1.0, sum(pr for pr in probs if pr <= obs + 1e-12))


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p from the two discordant cell counts (A-only, B-only)."""
    return _binom_two_sided(min(b, c), b + c)


def sign_test(diffs: list[float]) -> dict:
    """Two-sided sign test on paired differences (ties dropped)."""
    pos = sum(1 for d in diffs if d > TOL)
    neg = sum(1 for d in diffs if d < -TOL)
    return {"n": len(diffs), "pos": pos, "neg": neg, "tie": len(diffs) - pos - neg,
            "p": _binom_two_sided(min(pos, neg), pos + neg)}


# -- per-run helpers (operate on the dicts compute_metrics emits) ---------------
def _true(round_elem) -> set:
    return {e for e in round_elem if str(e).startswith("def:")}


def round0_recall(run: dict):
    n = run.get("n_defects") or 0
    re_ = run.get("round_elements")
    if not n or not re_:
        return None
    return len(_true(re_[0])) / n


def distinct_defects_found(run: dict) -> set:
    found: set = set()
    for r in run.get("round_elements", []):
        found |= _true(r)
    return found


def late_defects(run: dict) -> set:
    """Defects whose canonical element first appears at round >= 1 (never in round 0)."""
    re_ = run.get("round_elements", [])
    if not re_:
        return set()
    r0 = _true(re_[0])
    later: set = set()
    for r in re_[1:]:
        later |= _true(r)
    return later - r0


def by_artifact(runs) -> dict:
    g = defaultdict(list)
    for r in runs:
        g[r["artifact_id"]].append(r)
    return g


def _majority(labels):
    return Counter(labels).most_common(1)[0][0]


# -- the comparison -------------------------------------------------------------
def compare_arms(runs_a, runs_b, cont_keys, regime_labels=("contractive-to-correct", "false-convergence")):
    """Item-paired comparison of two arms over the artifacts present in both.

    Continuous metrics: per-artifact mean across replicate runs, then a paired sign
    test on the A-B differences. Regime labels: per-artifact majority across
    replicates, then exact McNemar on the discordant artifacts. Diagnostics pool over
    all runs. Returns a nested dict of results (see ``arm_stats.py`` for formatting).
    """
    A, B = by_artifact(runs_a), by_artifact(runs_b)
    arts = sorted(set(A) & set(B))
    out = {"n_artifacts": len(arts), "continuous": {}, "regime": {}, "diagnostics": {}}

    for key in cont_keys:
        pa = [mean(r[key] for r in A[a]) for a in arts]
        pb = [mean(r[key] for r in B[a]) for a in arts]
        diffs = [x - y for x, y in zip(pa, pb)]
        out["continuous"][key] = {**sign_test(diffs), "mean_a": mean(pa), "mean_b": mean(pb),
                                  "mean_diff": mean(diffs) if diffs else 0.0}

    for lab in regime_labels:
        b = c = ra_n = rb_n = 0
        for a in arts:
            ra = _majority([r["regime"] for r in A[a]]) == lab
            rb = _majority([r["regime"] for r in B[a]]) == lab
            ra_n += ra
            rb_n += rb
            if ra and not rb:
                b += 1
            elif rb and not ra:
                c += 1
        n = max(len(arts), 1)
        out["regime"][lab] = {"a_only": b, "b_only": c, "p": mcnemar_exact(b, c),
                              "rate_a": ra_n / n, "rate_b": rb_n / n}

    out["diagnostics"] = _diagnostics(runs_a, runs_b, A, B, arts)
    return out


def _diagnostics(runs_a, runs_b, A, B, arts) -> dict:
    # round-0 recall balance (should be ~equal: round 0 is the identical cold prompt)
    r0 = []
    for a in arts:
        va = [round0_recall(r) for r in A[a] if round0_recall(r) is not None]
        vb = [round0_recall(r) for r in B[a] if round0_recall(r) is not None]
        if va and vb:
            r0.append(mean(va) - mean(vb))
    r0a = mean([round0_recall(r) for r in runs_a if round0_recall(r) is not None] or [0])
    r0b = mean([round0_recall(r) for r in runs_b if round0_recall(r) is not None] or [0])

    def late_rate(runs):
        late = sum(len(late_defects(r)) for r in runs)
        opp = sum(r.get("stabilized_round", 0) for r in runs)  # Expert D: normalize by Σ stabilized_round
        return {"late_defects": late, "opportunity": opp, "per_opportunity": (late / opp if opp else 0.0)}

    def distinct(runs):
        found = sum(len(distinct_defects_found(r)) for r in runs)
        total = sum(r.get("n_defects", 0) for r in runs)
        return {"found": found, "total": total, "rate": (found / total if total else 0.0)}

    return {
        "round0_recall": {**sign_test(r0), "mean_a": r0a, "mean_b": r0b},
        "late_discovery": {"a": late_rate(runs_a), "b": late_rate(runs_b)},
        "distinct_defects": {"a": distinct(runs_a), "b": distinct(runs_b)},
    }
