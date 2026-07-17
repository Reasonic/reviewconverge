"""Tests for the item-paired arm-comparison stats + M4 diagnostics."""

import pytest

from reviewconverge.metrics.armstats import (
    compare_arms,
    distinct_defects_found,
    late_defects,
    mcnemar_exact,
    round0_recall,
    sign_test,
)


def test_mcnemar_exact_known():
    assert mcnemar_exact(0, 0) == pytest.approx(1.0)
    assert mcnemar_exact(5, 0) == pytest.approx(2 * 0.5 ** 5)   # all discordant one way
    assert mcnemar_exact(3, 3) > 0.5                            # symmetric -> non-significant


def test_sign_test_known():
    r = sign_test([1, 1, 1, 1, -1])
    assert r["pos"] == 4 and r["neg"] == 1 and r["tie"] == 0
    assert sign_test([1, -1])["p"] == pytest.approx(1.0)
    z = sign_test([0.0, 0.0])
    assert z["tie"] == 2 and z["p"] == pytest.approx(1.0)


def _run(aid, cfg, regime, churn, round_elems, ndef, stab):
    return {"artifact_id": aid, "config_id": cfg, "regime": regime, "mean_churn": churn,
            "oscillation_degree": 0, "stabilized_round": stab, "terminal_precision": 1.0,
            "terminal_false_fraction": 0.0, "terminal_recall": 1.0,
            "round_elements": round_elems, "n_defects": ndef}


def test_round_element_diagnostics():
    run = _run("c1", "A", "contractive-to-correct", 0.1,
               [["def:d1"], ["def:d1", "def:d2"], ["def:d1", "def:d2", "false:0"]], 3, 1)
    assert round0_recall(run) == pytest.approx(1 / 3)
    assert distinct_defects_found(run) == {"def:d1", "def:d2"}
    assert late_defects(run) == {"def:d2"}   # d2 first appears at round 1


def test_compare_arms_structure_and_direction():
    # Arm A: lower churn + contractive-to-correct on both artifacts.
    A = [_run("c1", "A", "contractive-to-correct", 0.1, [["def:d1"]], 1, 1),
         _run("c2", "A", "contractive-to-correct", 0.1, [["def:d1"]], 1, 1)]
    B = [_run("c1", "B", "oscillatory-churn", 0.5, [["def:d1"]], 1, 3),
         _run("c2", "B", "oscillatory-churn", 0.5, [["def:d1"]], 1, 3)]
    res = compare_arms(A, B, ["mean_churn"])
    assert res["n_artifacts"] == 2
    assert res["continuous"]["mean_churn"]["mean_diff"] == pytest.approx(-0.4)
    assert res["continuous"]["mean_churn"]["neg"] == 2          # A lower on both
    assert res["regime"]["contractive-to-correct"]["a_only"] == 2   # A CC, B not, on both


def test_compare_arms_pools_replicates_by_artifact():
    # Two replicate runs of arm A on the same artifact -> averaged, one pair.
    A = [_run("c1", "A", "contractive-to-correct", 0.2, [["def:d1"]], 1, 1),
         _run("c1", "A", "contractive-to-correct", 0.4, [["def:d1"]], 1, 1)]
    B = [_run("c1", "B", "contractive-to-correct", 0.3, [["def:d1"]], 1, 1)]
    res = compare_arms(A, B, ["mean_churn"])
    assert res["n_artifacts"] == 1
    assert res["continuous"]["mean_churn"]["mean_a"] == pytest.approx(0.3)  # (0.2+0.4)/2
