"""Metric suite + regime classifier (M3) — the minimum preprintable unit.

Turns a ``RunTrajectory`` (per-round finding-sets) into convergence metrics and a
regime label, all defined on the *finding-set trajectory* as the unit of analysis
(PLANS §5). Identity across rounds and against seeded ground truth is resolved by
the judged :class:`~reviewconverge.matcher.Matcher` (M2-audit constraint: the
deterministic matcher mis-scores real field findings).

Pipeline:
    canonicalize_trajectory(run, defects, matcher, gray_zones)  # -> stable element sets
        -> compute_trajectory_metrics(canon, meta)             # -> TrajectoryMetrics
        -> classify_regime(metrics)                            # -> regime label

Metrics: churn/turnover (Jaccard), false-finding fraction, true-finding attrition,
oscillation degree, stabilized-round (distance-to-fixed-point), terminal
precision/recall (fixed-point correctness). Regimes: contractive-to-correct |
false-convergence | oscillatory-churn | divergent — rule-based, thresholds
documented in :mod:`.regime`.
"""

from .canonical import (
    CanonicalRound,
    CanonicalTrajectory,
    canonicalize_trajectory,
    cluster_findings,
)
from .regime import (
    CORRECT_MAX_FALSE,
    CORRECT_RECALL,
    REGIMES,
    classify_regime,
    is_terminal_correct,
    regime_distribution,
)
from .suite import (
    TrajectoryMetrics,
    churn_per_round,
    compute_trajectory_metrics,
    false_fraction_per_round,
    jaccard_distance,
    oscillation_degree,
    stabilized_round,
    terminal_precision_recall,
    true_attrition_events,
)

__all__ = [
    # canonical
    "canonicalize_trajectory",
    "cluster_findings",
    "CanonicalTrajectory",
    "CanonicalRound",
    # suite
    "compute_trajectory_metrics",
    "TrajectoryMetrics",
    "jaccard_distance",
    "churn_per_round",
    "false_fraction_per_round",
    "true_attrition_events",
    "oscillation_degree",
    "stabilized_round",
    "terminal_precision_recall",
    # regime
    "classify_regime",
    "is_terminal_correct",
    "regime_distribution",
    "REGIMES",
    "CORRECT_RECALL",
    "CORRECT_MAX_FALSE",
]
