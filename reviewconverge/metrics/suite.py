"""Per-run trajectory metrics (M3).

All metrics operate on a :class:`~reviewconverge.metrics.canonical.CanonicalTrajectory`
— a sequence of per-round sets of stable element ids, with a truth map. This is the
"finding-set trajectory as the unit of analysis" (PLANS §5): convergence is measured
as set dynamics, correctness against the seeded ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .canonical import CanonicalTrajectory

_DEF_PREFIX = "def:"


def jaccard_distance(a: set, b: set) -> float:
    """Turnover between two sets in ``[0, 1]``; 0 for two empty sets."""
    if not a and not b:
        return 0.0
    return 1.0 - len(a & b) / len(a | b)


def churn_per_round(sets: list[set]) -> list[float]:
    """Jaccard distance between each consecutive pair of finding-sets."""
    return [jaccard_distance(sets[i], sets[i + 1]) for i in range(len(sets) - 1)]


def false_fraction_per_round(sets: list[set], is_true: dict[str, bool]) -> list[float]:
    """Fraction of each round's finding-set that is a false (non-seeded) finding."""
    out = []
    for s in sets:
        out.append(sum(1 for e in s if not is_true.get(e, False)) / len(s) if s else 0.0)
    return out


def true_attrition_events(sets: list[set], is_true: dict[str, bool]) -> int:
    """Count transitions where a *true* finding present in round r is gone in r+1."""
    events = 0
    for i in range(len(sets) - 1):
        for e in sets[i]:
            if is_true.get(e, False) and e not in sets[i + 1]:
                events += 1
    return events


def _oscillates(pattern: list[bool]) -> bool:
    """Does a presence pattern contain a present → absent → present (leave-and-return)?"""
    state = 0  # 0: before first present, 1: present seen, 2: absent-after-present seen
    for p in pattern:
        if state == 0 and p:
            state = 1
        elif state == 1 and not p:
            state = 2
        elif state == 2 and p:
            return True
    return False


def oscillation_degree(sets: list[set]) -> int:
    """Number of elements that leave the finding-set and later return."""
    all_elems: set[str] = set().union(*sets) if sets else set()
    return sum(1 for e in all_elems if _oscillates([e in s for s in sets]))


def stabilized_round(sets: list[set]) -> int:
    """Smallest round index r with ``sets[r] == sets[r+1] == ... == sets[-1]``.

    The round at which the finding-set reaches its final value and stops changing.
    Equals ``len-1`` if the last round still differs from the previous one.
    """
    n = len(sets)
    if n <= 1:
        return 0
    start = n - 1
    for i in range(n - 2, -1, -1):
        if sets[i] == sets[-1]:
            start = i
        else:
            break
    return start


def terminal_precision_recall(
    sets: list[set], is_true: dict[str, bool], defect_ids: list[str]
) -> tuple[float, float]:
    """Precision/recall of the terminal finding-set vs seeded ground truth.

    Precision = fraction of the terminal set that are true findings.
    Recall = fraction of seeded defects present in the terminal set.
    """
    term = sets[-1] if sets else set()
    true_elems = {e for e in term if is_true.get(e, False)}
    matched_defects = {e[len(_DEF_PREFIX):] for e in true_elems if e.startswith(_DEF_PREFIX)}
    precision = len(true_elems) / len(term) if term else 1.0
    recall = len(matched_defects) / len(defect_ids) if defect_ids else 1.0
    return precision, recall


@dataclass
class TrajectoryMetrics:
    """The per-run metric bundle the regime classifier and reports consume."""

    run_id: str
    artifact_id: str
    config_id: str
    model_id: str
    n_rounds: int
    set_sizes: list[int]
    churn: list[float]
    mean_churn: float
    late_churn: float                 # churn of the final transition (settling signal)
    false_fraction: list[float]
    terminal_false_fraction: float
    true_attrition_events: int
    oscillation_degree: int
    stabilized_round: int
    converged: bool                   # last two rounds identical
    terminal_precision: float
    terminal_recall: float
    n_defects: int

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("churn", "false_fraction"):
            d[k] = [round(x, 4) for x in d[k]]
        for k in ("mean_churn", "late_churn", "terminal_false_fraction",
                  "terminal_precision", "terminal_recall"):
            d[k] = round(d[k], 4)
        return d


def compute_trajectory_metrics(canon: CanonicalTrajectory, meta: dict) -> TrajectoryMetrics:
    """Compute all per-run metrics from a canonicalized trajectory.

    ``meta`` supplies run identity (run_id/artifact_id/config_id/model_id).
    """
    sets = canon.round_sets()
    is_true = canon.element_is_true
    churn = churn_per_round(sets)
    ff = false_fraction_per_round(sets, is_true)
    prec, rec = terminal_precision_recall(sets, is_true, canon.defect_ids)
    converged = len(sets) >= 2 and sets[-1] == sets[-2]
    return TrajectoryMetrics(
        run_id=meta.get("run_id", ""),
        artifact_id=meta.get("artifact_id", ""),
        config_id=meta.get("config_id", ""),
        model_id=meta.get("model_id", ""),
        n_rounds=len(sets),
        set_sizes=[len(s) for s in sets],
        churn=churn,
        mean_churn=sum(churn) / len(churn) if churn else 0.0,
        late_churn=churn[-1] if churn else 0.0,
        false_fraction=ff,
        terminal_false_fraction=ff[-1] if ff else 0.0,
        true_attrition_events=true_attrition_events(sets, is_true),
        oscillation_degree=oscillation_degree(sets),
        stabilized_round=stabilized_round(sets),
        converged=converged,
        terminal_precision=prec,
        terminal_recall=rec,
        n_defects=len(canon.defect_ids),
    )
