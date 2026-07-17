"""Rule-based regime classifier (M3).

Labels each run's trajectory with one of four regimes. The classifier is
**rule-based on the metrics with documented thresholds — never an LLM judgment**
(PLANS §5): an LLM deciding "did this converge correctly?" would reintroduce the
hallucination the benchmark measures.

Regimes:
- ``contractive-to-correct`` — the finding-set settles (last two rounds identical)
  and the terminal set is correct (recovers the seeded defects with little noise).
- ``false-convergence`` — the finding-set settles but on the WRONG answer (misses
  seeded defects and/or is dominated by false findings). The headline failure mode.
- ``oscillatory-churn`` — never settles; findings leave and return / the set keeps
  turning over without net growth.
- ``divergent`` — never settles and the finding-set keeps *growing* to the end.
"""

from __future__ import annotations

from .suite import TrajectoryMetrics

# --- documented thresholds ------------------------------------------------
CORRECT_RECALL = 0.80        # terminal recall at/above which the fixed point is "correct"
CORRECT_MAX_FALSE = 0.34     # terminal false-fraction at/below which it is "correct"

CONTRACTIVE_TO_CORRECT = "contractive-to-correct"
FALSE_CONVERGENCE = "false-convergence"
OSCILLATORY_CHURN = "oscillatory-churn"
DIVERGENT = "divergent"

REGIMES = (CONTRACTIVE_TO_CORRECT, FALSE_CONVERGENCE, OSCILLATORY_CHURN, DIVERGENT)


def is_terminal_correct(m: TrajectoryMetrics) -> bool:
    """Terminal finding-set recovers the defects with acceptable noise."""
    return m.terminal_recall >= CORRECT_RECALL and m.terminal_false_fraction <= CORRECT_MAX_FALSE


def classify_regime(m: TrajectoryMetrics) -> str:
    """Assign one regime label from the per-run metrics."""
    if m.converged:
        return CONTRACTIVE_TO_CORRECT if is_terminal_correct(m) else FALSE_CONVERGENCE
    # Not converged: growing-to-the-end is divergent; anything else is churn.
    sizes = m.set_sizes
    grew_to_end = bool(sizes) and sizes[-1] > sizes[0] and sizes[-1] == max(sizes)
    if grew_to_end and m.oscillation_degree == 0:
        return DIVERGENT
    return OSCILLATORY_CHURN


def regime_distribution(labels: list[str]) -> dict[str, float]:
    """Rate of each regime across a batch of runs (fractions, summing to 1)."""
    n = len(labels)
    return {r: (labels.count(r) / n if n else 0.0) for r in REGIMES}
