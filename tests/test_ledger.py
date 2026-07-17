"""Tests for the monotone evidence-ledger intervention arm (M4, Arm 1).

Split into (a) the network-free ledger mechanics — section parsing, grounded
retirement, monotone update — and (b) a loop-level test that the arm actually
enforces persistence and grounded retirement end-to-end against a stub reviewer.
"""

from __future__ import annotations

import pytest

from reviewconverge.schema import Finding, Location, Severity
from reviewconverge.harness import (
    FindingExtractor,
    LoopConfig,
    ReviewLoop,
    build_ledger_review_user_prompt,
    parse_retirements,
    split_sections,
    update_ledger,
)


def _f(claim, unit="a.py", start=None, end=None):
    return Finding(id="x", claim=claim, location=Location(unit, start, end))


# -- section split --------------------------------------------------------
def test_split_sections_normal_order():
    text = ("RETIRE:\n- item 2: the bound is actually correct here\n\n"
            "NEW ISSUES:\n1. missing null check at line 9")
    retire, new = split_sections(text)
    assert "item 2" in retire and "bound is actually correct" in retire
    assert "missing null check" in new and "item 2" not in new


def test_split_sections_fallback_when_unstructured():
    # No headers -> retire nothing, whole reply is candidate-new (monotone default).
    retire, new = split_sections("1. some issue at line 4\n2. another at line 9")
    assert retire == ""
    assert "some issue" in new and "another" in new


def test_split_sections_handles_headers_either_order():
    text = "NEW ISSUES:\nnone\n\nRETIRE:\nitem 1: not a real problem, value is fine"
    retire, new = split_sections(text)
    assert "not a real problem" in retire
    assert new.strip().startswith("none")


# -- grounded retirement --------------------------------------------------
def test_parse_retirements_requires_grounds_and_range():
    block = ("item 1: this is fine because the guard already covers it\n"
             "item 2\n"                       # bare number -> no grounds -> ignored
             "3: x\n"                          # too-short reason -> ignored
             "item 9: out of range so ignored")
    assert parse_retirements(block, ledger_size=4) == {0}  # only item 1 retires


def test_parse_retirements_various_line_shapes():
    block = ("- item 2 — the value is validated upstream already\n"
             "4) actually correct per the spec section\n")
    assert parse_retirements(block, ledger_size=5) == {1, 3}


# -- monotone update ------------------------------------------------------
def test_update_ledger_is_monotone_by_default():
    ledger = [_f("off by one in the loop bound"), _f("divisor never checked for zero")]
    # Retire nothing, add nothing -> ledger is unchanged (persistence by default).
    out = update_ledger(ledger, retired_idx=set(), new_findings=[])
    assert [f.claim for f in out] == [f.claim for f in ledger]


def test_update_ledger_drops_only_retired_and_appends_new():
    ledger = [_f("off by one in the loop bound"), _f("divisor never checked for zero")]
    new = [_f("return value ignores the remainder", start=9)]
    out = update_ledger(ledger, retired_idx={0}, new_findings=new)
    claims = [f.claim for f in out]
    assert "off by one in the loop bound" not in claims       # retired
    assert "divisor never checked for zero" in claims          # persisted
    assert "return value ignores the remainder" in claims      # added


def test_update_ledger_dedups_rediscovered_new_finding():
    ledger = [_f("the divisor is never checked for zero", start=5)]
    # Same issue, re-surfaced as "new" with compatible location -> not re-added.
    dup = [_f("the divisor is never checked for zero", start=5)]
    out = update_ledger(ledger, retired_idx=set(), new_findings=dup)
    assert len(out) == 1


# -- prompt ---------------------------------------------------------------
def test_ledger_prompt_lists_items_and_demands_two_sections():
    ledger = [_f("off by one in the loop bound", start=4)]
    p = build_ledger_review_user_prompt("CODE", "code", ledger)
    assert "off by one in the loop bound" in p
    assert "RETIRE:" in p and "NEW ISSUES:" in p
    assert "stays in the ledger" in p  # the monotone rule is stated to the reviewer


# -- loop-level end-to-end ------------------------------------------------
class _LedgerReviewer:
    """Round 0: reports one real + one bogus finding. Rounds >0: retires the bogus
    one (grounded) and adds nothing — exercising persist + grounded-retire."""

    model = "ledger-stub"
    family = "stub"

    def __init__(self):
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        if "RETIRE:" in user:  # a ledger round (r>0)
            return ("RETIRE:\nitem 2: on a second look the config value is valid, "
                    "not a bug\n\nNEW ISSUES:\nnone")
        return ("1. off by one at line 4. Evidence: bound.\n"
                "2. timeout is misconfigured at line 9. Evidence: too low.")


class _TwoFindingExtractor:
    """Extracts the two round-0 findings; extracts nothing from a 'none' new-block."""

    family = "stub"

    def complete(self, system, user):
        if "off by one" in user:
            return ('[{"claim":"off by one","unit":"a.py","start":4,"end":4,"severity":"major"},'
                    '{"claim":"timeout misconfigured","unit":"a.py","start":9,"end":9,"severity":"minor"}]')
        return "[]"


def test_ledger_loop_persists_then_grounded_retires():
    rev = _LedgerReviewer()
    loop = ReviewLoop(rev, FindingExtractor(_TwoFindingExtractor()),
                      LoopConfig("single-ledger", rounds=3, ledger=True))
    res = loop.run("code", "code", "code-0001", run_id="r")
    rounds = res.trajectory.rounds
    r0 = {f.claim for f in rounds[0].findings}
    assert r0 == {"off by one", "timeout misconfigured"}       # both seeded round 0
    # Round 1 retires the bogus one (grounded) and keeps the real one -> ledger of 1.
    r1 = {f.claim for f in rounds[1].findings}
    assert r1 == {"off by one"}
    # Monotone: round 2 keeps it (nothing new, nothing retired) -> stable fixed point.
    assert {f.claim for f in rounds[2].findings} == {"off by one"}


def test_ledger_config_implies_memory_and_rejects_panel():
    cfg = LoopConfig("single-ledger", ledger=True)
    assert cfg.memory is True         # ledger implies memory
    with pytest.raises(ValueError):
        LoopConfig("bad", ledger=True, panel_size=3)


# -- structured-memory control arm (M4 confound disentangler) -------------
def test_parse_retirements_grounds_gate_toggle():
    block = "item 2\nitem 3: on reflection the guard already covers this"
    assert parse_retirements(block, ledger_size=4) == {2}                      # gated: only item 3
    assert parse_retirements(block, ledger_size=4, min_reason_words=0) == {1, 2}  # ungated: both


class _BareRetireReviewer:
    """Round 0: two findings. Ledger rounds: retire item 2 with NO grounds (bare number)."""

    model = "sm-stub"
    family = "stub"

    def complete(self, system, user):
        if "RETIRE:" in user:
            return "RETIRE:\nitem 2\n\nNEW ISSUES:\nnone"
        return ("1. off by one at line 4. Evidence: bound.\n"
                "2. timeout misconfigured at line 9. Evidence: too low.")


def test_structured_memory_retires_ungated_where_full_ledger_keeps():
    # Same reviewer, same prompt, same carry-forward — only the grounds gate differs.
    gated = ReviewLoop(_BareRetireReviewer(), FindingExtractor(_TwoFindingExtractor()),
                       LoopConfig("ledger", rounds=2, ledger=True))
    r_gated = gated.run("code", "code", "code-0001", run_id="r")
    # Full ledger: a bare "item 2" is not grounded -> nothing retired, both persist.
    assert {f.claim for f in r_gated.trajectory.rounds[1].findings} == {"off by one", "timeout misconfigured"}

    sm = ReviewLoop(_BareRetireReviewer(), FindingExtractor(_TwoFindingExtractor()),
                    LoopConfig("structured-memory", rounds=2, ledger=True, grounded_retire=False))
    r_sm = sm.run("code", "code", "code-0001", run_id="r")
    # Structured-memory: retirement on say-so -> item 2 drops, only the first persists.
    assert {f.claim for f in r_sm.trajectory.rounds[1].findings} == {"off by one"}
