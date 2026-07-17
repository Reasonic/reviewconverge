"""Tests for the M3 metric suite + regime classifier. Offline, mock matcher."""

from __future__ import annotations

from reviewconverge.schema import (
    Finding,
    Location,
    RoundFindingSet,
    RunTrajectory,
    SeededDefect,
    Severity,
)
from reviewconverge.matcher import GroundTruthMatch
from reviewconverge.metrics import (
    canonicalize_trajectory,
    churn_per_round,
    classify_regime,
    compute_trajectory_metrics,
    jaccard_distance,
    oscillation_degree,
    regime_distribution,
    stabilized_round,
    terminal_precision_recall,
    true_attrition_events,
)


# -- a mock matcher: a finding's claim IS its issue tag ("d1"/"d2"/"X"/"gray") ---
class MockMatcher:
    """Edge-based mock mirroring the real 1:1 assignment. ``matches`` optionally maps
    a claim to ``[(defect_id, score), ...]`` edges (for magnet / over-broad-paraphrase
    tests); by default a claim matches the defect whose id equals it, at score 1.0."""

    def __init__(self, gray_claims=(), matches=None):
        self.gray = set(gray_claims)
        self.matches = matches or {}

    def same_finding(self, a: Finding, b: Finding) -> bool:
        return a.claim == b.claim

    def match_to_ground_truth(self, findings, defects, gray_zones=None, bijective=True):
        didx = {d.id: k for k, d in enumerate(defects)}
        edges = []  # (score, finding_idx, defect_idx)
        for i, f in enumerate(findings):
            if f.claim in self.matches:
                edges += [(s, i, didx[did]) for did, s in self.matches[f.claim] if did in didx]
            elif f.claim in didx:
                edges.append((1.0, i, didx[f.claim]))
        edges.sort(reverse=True)
        matched_any = {i for _s, i, _k in edges}
        used_f, used_d, tp = set(), set(), {}
        for _s, i, k in edges:
            if i in used_f or (bijective and k in used_d):
                continue
            tp[i] = defects[k].id
            used_f.add(i)
            used_d.add(k)
        false, gray = [], []
        for i, f in enumerate(findings):
            if i in used_f or i in matched_any:  # assigned, or a duplicate of a found defect
                continue
            (gray if f.claim in self.gray else false).append(i)
        missed = [d.id for k, d in enumerate(defects) if k not in used_d]
        return GroundTruthMatch(true_positives=tp, missed=missed,
                                false_findings=false, gray_findings=gray)


def _traj(rounds_of_claims):
    rounds = [
        RoundFindingSet(round_index=i,
                        findings=[Finding(id=f"r{i}-f{j}", claim=c) for j, c in enumerate(cs)])
        for i, cs in enumerate(rounds_of_claims)
    ]
    return RunTrajectory(run_id="t", artifact_id="a", config_id="c", model_id="m", rounds=rounds)


def _defects(*ids):
    return [SeededDefect(id=i, description=i, location=Location("u"), severity=Severity.MAJOR)
            for i in ids]


def _metrics(rounds_of_claims, defect_ids=("d1", "d2"), gray_claims=()):
    canon = canonicalize_trajectory(_traj(rounds_of_claims), _defects(*defect_ids),
                                    MockMatcher(gray_claims))
    return compute_trajectory_metrics(canon, {"run_id": "t", "artifact_id": "a",
                                              "config_id": "c", "model_id": "m"})


# -- pure metric functions ------------------------------------------------
def test_jaccard_and_churn():
    assert jaccard_distance(set(), set()) == 0.0
    assert jaccard_distance({"a"}, {"a"}) == 0.0
    assert jaccard_distance({"a"}, {"b"}) == 1.0
    assert jaccard_distance({"a", "b"}, {"a"}) == 0.5
    assert churn_per_round([{"a"}, {"a"}, {"a", "b"}]) == [0.0, 0.5]


def test_oscillation_and_stabilized_and_terminal():
    # d2 leaves and returns
    assert oscillation_degree([{"a", "d2"}, {"a"}, {"a", "d2"}]) == 1
    assert oscillation_degree([{"a"}, {"a", "b"}, {"a", "b"}]) == 0
    assert stabilized_round([{"a"}, {"a", "b"}, {"a", "b"}]) == 1
    assert stabilized_round([{"a"}, {"a", "b"}]) == 1  # last differs -> stable only at end
    p, r = terminal_precision_recall([{"def:d1", "false:0"}], {"def:d1": True, "false:0": False}, ["d1", "d2"])
    assert p == 0.5 and r == 0.5


def test_true_attrition():
    sets = [{"def:d1", "def:d2"}, {"def:d1"}]
    assert true_attrition_events(sets, {"def:d1": True, "def:d2": True}) == 1


# -- within-round dedup ---------------------------------------------------
def test_within_round_dedup():
    # a reviewer lists d1 twice + one false, in a single round
    canon = canonicalize_trajectory(_traj([["d1", "d1", "X"]]), _defects("d1", "d2"), MockMatcher())
    assert canon.rounds[0].elements == {"def:d1", "false:0"}  # d1 counted once


def test_two_findings_two_defects_both_counted():
    # Regression for the over-merge bug (code-0003): distinct findings hitting
    # distinct defects must both be counted — matching happens before any dedup.
    canon = canonicalize_trajectory(_traj([["d1", "d2"]]), _defects("d1", "d2"), MockMatcher())
    assert canon.rounds[0].elements == {"def:d1", "def:d2"}


def test_magnet_defect_does_not_collapse_recall():
    # Regression for the 2026-07-06 magnet bug (code-0015): three findings each
    # match their own defect AND an over-broad "magnet" defect d3. The magnet's true
    # owner ("c") scores highest on it, so the 1:1 assignment gives each finding its
    # own defect. bijective=False collapses all three onto d3 (recall 1/3); the 1:1
    # default must recover recall 1.0.
    matches = {"a": [("d1", 0.85), ("d3", 0.95)],
               "b": [("d2", 0.85), ("d3", 0.95)],
               "c": [("d3", 1.0)]}
    canon = canonicalize_trajectory(_traj([["a", "b", "c"]]),
                                    _defects("d1", "d2", "d3"), MockMatcher(matches=matches))
    assert canon.rounds[0].elements == {"def:d1", "def:d2", "def:d3"}
    _, r = terminal_precision_recall(canon.round_sets(), canon.element_is_true, canon.defect_ids)
    assert r == 1.0


def test_within_defect_duplicate_is_not_a_false_finding():
    # Two findings both correctly identify d1: one true element, the other a
    # duplicate (dropped) — NOT a hallucination that would deflate precision.
    canon = canonicalize_trajectory(_traj([["d1", "d1"]]), _defects("d1", "d2"), MockMatcher())
    assert canon.rounds[0].elements == {"def:d1"}   # deduped, no false element
    p, _ = terminal_precision_recall(canon.round_sets(), canon.element_is_true, canon.defect_ids)
    assert p == 1.0


# -- regimes --------------------------------------------------------------
def test_regime_contractive_to_correct():
    m = _metrics([["d1"], ["d1", "d2"], ["d1", "d2"], ["d1", "d2"]])
    assert m.converged and m.terminal_recall == 1.0 and m.terminal_false_fraction == 0.0
    assert classify_regime(m) == "contractive-to-correct"


def test_regime_false_convergence():
    # settles on {d1, X}: stable but misses d2 -> wrong fixed point
    m = _metrics([["d1", "X"], ["d1", "X"], ["d1", "X"]])
    assert m.converged and m.terminal_recall == 0.5
    assert classify_regime(m) == "false-convergence"


def test_regime_oscillatory_churn():
    m = _metrics([["d1", "d2"], ["d1"], ["d1", "d2"], ["d1"]])
    assert not m.converged and m.oscillation_degree >= 1
    assert classify_regime(m) == "oscillatory-churn"


def test_regime_divergent():
    m = _metrics([["d1"], ["d1", "X"], ["d1", "X", "Y"], ["d1", "X", "Y", "Z"]])
    assert not m.converged and m.oscillation_degree == 0
    assert m.set_sizes == [1, 2, 3, 4]
    assert classify_regime(m) == "divergent"


def test_gray_findings_excluded():
    # 'gray' finding is neither true nor false; dropped from the set
    canon = canonicalize_trajectory(_traj([["d1", "gray"]]), _defects("d1"), MockMatcher(gray_claims={"gray"}))
    assert canon.rounds[0].elements == {"def:d1"}


def test_regime_distribution():
    dist = regime_distribution(["divergent", "divergent", "false-convergence", "contractive-to-correct"])
    assert dist["divergent"] == 0.5 and dist["false-convergence"] == 0.25
    assert abs(sum(dist.values()) - 1.0) < 1e-9
