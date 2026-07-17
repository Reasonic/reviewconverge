"""Tests for the iterative-review harness (M2). All offline — no network."""

from __future__ import annotations

import pytest

from reviewconverge.schema import Finding, Location, RunTrajectory, Severity
from reviewconverge.harness import (
    FindingExtractor,
    LoopConfig,
    ReviewLoop,
    build_review_user_prompt,
)
from reviewconverge.harness.extractor import _parse_findings_json


# -- extractor parsing ----------------------------------------------------
def test_parse_findings_plain_json():
    raw = ('[{"claim":"off by one in bound","unit":"a.py","start":4,"end":4,'
           '"severity":"major","evidence":"loop runs one past end"}]')
    fs = _parse_findings_json(raw, 0)
    assert len(fs) == 1
    f = fs[0]
    assert f.claim == "off by one in bound" and f.id == "r0-f0"
    assert f.location == Location("a.py", 4, 4) and f.severity is Severity.MAJOR
    assert f.evidence == "loop runs one past end"


def test_parse_findings_fenced_and_prose_wrapped():
    fenced = '```json\n[{"claim":"bad","unit":"x","start":null,"end":null,"severity":"minor"}]\n```'
    assert len(_parse_findings_json(fenced, 1)) == 1
    prose = 'Here you go:\n[{"claim":"issue","unit":"","severity":"info"}]\nDone.'
    fs = _parse_findings_json(prose, 2)
    assert len(fs) == 1 and fs[0].location is None  # empty unit -> unlocalized


def test_parse_findings_bad_and_empty():
    assert _parse_findings_json("not json at all", 0) == []
    assert _parse_findings_json("[]", 0) == []
    assert _parse_findings_json('[{"unit":"x"}]', 0) == []  # no claim -> skipped
    assert _parse_findings_json('{"claim":"x"}', 0) == []   # not a list


class _StubClient:
    model = "stub-1"
    family = "stub"

    def __init__(self, reply):
        self.reply = reply
        self.seen = []

    def complete(self, system, user):
        self.seen.append((system, user))
        return self.reply


def test_extractor_extract_and_empty_review():
    ext = FindingExtractor(_StubClient('[{"claim":"c","unit":"a","start":1,"end":1,"severity":"minor"}]'))
    fs = ext.extract("artifact", "1. c at line 1", 3)
    assert len(fs) == 1 and fs[0].id == "r3-f0"
    assert ext.extract("artifact", "   ", 0) == []  # empty review -> no call needed


# -- review prompt (memory) ----------------------------------------------
def test_review_prompt_includes_prior_findings_only_with_memory():
    prior = [Finding(id="r0-f0", claim="divisor never checked for zero",
                     location=Location("a.py", 5, 5), severity=Severity.MAJOR)]
    with_mem = build_review_user_prompt("ART", "code", prior)
    assert "divisor never checked for zero" in with_mem and "previous round" in with_mem
    without = build_review_user_prompt("ART", "code", None)
    assert "divisor never checked for zero" not in without


# -- loop -----------------------------------------------------------------
class _ReviewerSpy:
    model = "reviewer-x"
    family = "stub"

    def __init__(self):
        self.users = []

    def complete(self, system, user):
        self.users.append(user)
        return "1. off by one at line 4. Evidence: bound."


class _ExtractorStub:
    family = "stub"

    def complete(self, system, user):
        return '[{"claim":"off by one","unit":"a.py","start":4,"end":4,"severity":"major","evidence":"bound"}]'


def test_loop_runs_n_rounds_and_builds_trajectory():
    rev = _ReviewerSpy()
    loop = ReviewLoop(rev, FindingExtractor(_ExtractorStub()), LoopConfig("single-mem", rounds=3, memory=True))
    res = loop.run("code here", "code", "code-0001", run_id="run1", seed=7)
    traj = res.trajectory
    assert isinstance(traj, RunTrajectory)
    assert len(traj.rounds) == 3 and traj.config_id == "single-mem" and traj.seed == 7
    assert traj.model_id == "reviewer-x"
    assert all(len(r.findings) == 1 for r in traj.rounds)
    assert traj.rounds[2].findings[0].id == "r2-f0"
    assert res.reviewer_calls == 3
    # round-serialization round-trips
    assert res.to_dict()["trajectory"]["rounds"][0]["round_index"] == 0


def test_loop_memory_on_feeds_prior_findings():
    rev = _ReviewerSpy()
    loop = ReviewLoop(rev, FindingExtractor(_ExtractorStub()), LoopConfig("m", rounds=3, memory=True))
    loop.run("code", "code", "code-0001", run_id="r")
    assert "off by one" not in rev.users[0]      # round 0: no prior
    assert "off by one" in rev.users[1]          # round 1: prior fed back


def test_loop_memory_off_never_feeds_prior():
    rev = _ReviewerSpy()
    loop = ReviewLoop(rev, FindingExtractor(_ExtractorStub()), LoopConfig("nm", rounds=3, memory=False))
    loop.run("code", "code", "code-0001", run_id="r")
    assert all("off by one" not in u for u in rev.users)


def test_panel_unions_reviewers():
    rev = _ReviewerSpy()
    loop = ReviewLoop(rev, FindingExtractor(_ExtractorStub()), LoopConfig("panel", rounds=2, panel_size=3))
    res = loop.run("code", "code", "code-0001", run_id="r")
    assert res.reviewer_calls == 6                # 2 rounds x 3 reviewers
    assert all(len(rr.findings) == 3 for rr in res.trajectory.rounds)  # 3 reviewers unioned


def test_loop_config_validation():
    with pytest.raises(ValueError):
        LoopConfig("x", rounds=0)
    with pytest.raises(ValueError):
        LoopConfig("x", rounds=9)   # over MAX_ROUNDS
    with pytest.raises(ValueError):
        LoopConfig("x", panel_size=0)
