"""Tests for the finding-equivalence matcher (M1b)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from reviewconverge.schema import Finding, Location, Severity, SeededDefect
from reviewconverge.matcher import (
    DecisionCache,
    LocationCompat,
    Matcher,
    finding_fingerprint,
    location_compatibility,
    pair_key,
    text_similarity,
)
from reviewconverge.matcher.core import _max_cardinality_matching, GrayZone
from reviewconverge.matcher.validation import (
    build_gold_from_corpus,
    cohen_kappa,
    evaluate,
    self_agreement,
    threshold_sensitivity,
)


# -- similarity -----------------------------------------------------------
def test_text_similarity_bounds_and_identity():
    assert text_similarity("same text here", "same text here") == pytest.approx(1.0)
    assert 0.0 <= text_similarity("alpha beta", "gamma delta") <= 0.3
    s = text_similarity("off by one in the loop bound", "the loop bound is off by one")
    assert s > 0.6  # reordering, same content words


def test_location_compatibility():
    a = Location("file.py", 10, 12)
    assert location_compatibility(a, Location("file.py", 11, 15)) is LocationCompat.SAME
    assert location_compatibility(a, Location("file.py", 40, 41)) is LocationCompat.DISJOINT
    assert location_compatibility(a, Location("other.py", 10, 12)) is LocationCompat.DISJOINT
    assert location_compatibility(a, None) is LocationCompat.UNKNOWN
    # missing offsets ⇒ whole unit ⇒ overlap
    assert location_compatibility(Location("f"), Location("f", 5, 9)) is LocationCompat.SAME


# -- cache ----------------------------------------------------------------
def test_fingerprint_and_pair_key_order_independent():
    fa = finding_fingerprint("off by one", Location("f.py", 1, 2))
    fb = finding_fingerprint("off by one", Location("f.py", 9, 9))  # offsets ignored
    assert fa == fb  # same wording + unit ⇒ same fingerprint (offsets don't churn it)
    assert pair_key("z", "a") == pair_key("a", "z")


def test_fingerprint_scope_isolates_artifacts():
    # audit #4: two artifacts sharing a unit name + a normalized claim must NOT share a
    # decision-cache key. An artifact scope namespaces the fingerprint to prevent bleed.
    loc = Location("main.py", 1, 2)
    base = finding_fingerprint("shared claim text", loc)
    a = finding_fingerprint("shared claim text", loc, scope="code-0001")
    b = finding_fingerprint("shared claim text", loc, scope="code-0002")
    assert a != b                                   # isolated per artifact
    assert base != a                                # scoping changes the key…
    assert finding_fingerprint("shared claim text", loc) == base  # …default stays unscoped


def test_fingerprint_operator_awareness_optional():
    # audit #5: "n <= len" and "n >= len" are opposite claims that a punctuation-
    # stripping normalize collapses into one fingerprint. keep_operators separates them.
    loc = Location("f.py")
    assert finding_fingerprint("n <= len", loc) == finding_fingerprint("n >= len", loc)  # legacy
    assert (finding_fingerprint("n <= len", loc, keep_operators=True)
            != finding_fingerprint("n >= len", loc, keep_operators=True))  # #5 fix


def test_cache_roundtrip(tmp_path):
    c = DecisionCache()
    c.put("a", "b", True)
    c.put("c", "d", False)
    p = tmp_path / "cache.json"
    c.save(p)
    c2 = DecisionCache.load(p)
    assert c2.get("b", "a") is True
    assert c2.get("d", "c") is False
    assert c2.get("x", "y") is None


# -- decide_pair pipeline -------------------------------------------------
def test_lexical_high_same():
    m = Matcher(judge=None)
    d = m.decide_pair("the divisor is never checked for zero", None,
                      "the divisor is never checked for zero", None)
    assert d.same and d.method == "lexical-high"


def test_anchor_disjoint_different():
    m = Matcher(judge=None)
    d = m.decide_pair("alpha beta", Location("a.py", 1, 2),
                      "gamma delta", Location("b.py", 1, 2))
    assert (not d.same) and d.method == "anchor-disjoint"


def test_subset_finding_is_escalated_not_auto_passed():
    # audit #6: a terse finding that is a strict token-subset of a longer defect has a
    # high overlap coefficient but low symmetric similarity — it must go to the JUDGE,
    # not auto-pass as lexical-high (which would let a subset-hallucination score SAME).
    calls = {"n": 0}

    def different_judge(ta, la, tb, lb):
        calls["n"] += 1
        return False  # judge rules DIFFERENT

    m = Matcher(judge=different_judge)
    d = m.decide_pair("off by one", None,
                      "off by one error in the loop upper bound index calculation", None,
                      use_cache=False)
    assert calls["n"] == 1                       # the judge was consulted, not bypassed
    assert d.method == "llm" and d.same is False
    # a genuinely symmetric near-duplicate still auto-passes without the judge
    d2 = m.decide_pair("the divisor is never checked for zero", None,
                       "the divisor is never checked for zero", None, use_cache=False)
    assert d2.method == "lexical-high" and d2.same
    assert calls["n"] == 1                       # no extra judge call


def test_fallback_band_deterministic():
    # Force everything into the fallback band with extreme thresholds.
    m = Matcher(judge=None, tau_high=0.999, tau_low=0.0, tau_mid=0.5)
    d1 = m.decide_pair("loop bound is wrong", None, "loop bound is off", None, use_cache=False)
    d2 = m.decide_pair("loop bound is wrong", None, "loop bound is off", None, use_cache=False)
    assert d1.method == "lexical-fallback"
    assert d1.same == d2.same  # deterministic


def test_judge_majority_vote_and_cache_replay():
    calls = {"n": 0}

    def yes_judge(ta, la, tb, lb):
        calls["n"] += 1
        return True

    m = Matcher(judge=yes_judge, tau_high=0.999, tau_low=0.0, vote_k=3)
    d = m.decide_pair("wholly distinct phrasing one", None, "entirely different words two", None)
    assert d.same and d.method == "llm"
    assert d.votes == (True, True, True)
    assert calls["n"] == 3
    # second call replays from cache — no new judge calls
    d2 = m.decide_pair("wholly distinct phrasing one", None, "entirely different words two", None)
    assert d2.method == "cache" and d2.same
    assert calls["n"] == 3


# -- resumability: undecided verdicts must not be cached ------------------
class _CountingJudge:
    def __init__(self, verdict, decided):
        self.verdict, self.decided, self.calls = verdict, decided, 0

    def decide(self, ta, la, tb, lb):
        self.calls += 1
        return (self.verdict, self.decided)

    def __call__(self, ta, la, tb, lb):
        return self.decide(ta, la, tb, lb)[0]


def test_undecided_judge_verdict_is_not_cached():
    """A judge that fails to decide (all retries exhausted -> decided=False, e.g. the
    account ran out of credit mid-run) returns the conservative default but must NOT be
    cached, so a resume re-judges the pair instead of replaying a wrong DIFFERENT."""
    a, b = "the loop index can exceed the array bound", "possible out-of-range on the counter"
    loc = Location("f.py", 5, 5)  # same location + low overlap -> reaches the judge
    j = _CountingJudge(verdict=False, decided=False)
    m = Matcher(judge=j, cache=DecisionCache())
    d1 = m.decide_pair(a, loc, b, loc)
    assert d1.method == "llm" and d1.same is False
    assert len(m.cache) == 0          # undecided -> NOT cached
    m.decide_pair(a, loc, b, loc)     # resume: judge is consulted again
    assert j.calls == 2


def test_decided_judge_verdict_is_cached():
    """Control: a genuinely decided verdict IS cached and replayed (no second call)."""
    a, b = "the loop index can exceed the array bound", "possible out-of-range on the counter"
    loc = Location("f.py", 5, 5)
    j = _CountingJudge(verdict=True, decided=True)
    m = Matcher(judge=j, cache=DecisionCache())
    m.decide_pair(a, loc, b, loc)
    m.decide_pair(a, loc, b, loc)
    assert j.calls == 1 and len(m.cache) == 1


# -- set matching ---------------------------------------------------------
def _f(i, claim, unit="f.py", start=None, end=None):
    return Finding(id=i, claim=claim, location=Location(unit, start, end))


def test_match_bipartite_one_to_one():
    m = Matcher(judge=None)
    a = [_f("a1", "the divisor is never checked for zero", start=5, end=5),
         _f("a2", "index goes one past the end of the list", start=20, end=20)]
    b = [_f("b1", "index goes one past the end of the list", start=20, end=20),
         _f("b2", "the divisor is never checked for zero", start=5, end=5)]
    res = m.match(a, b)
    assert sorted(res.matched) == [(0, 1), (1, 0)]
    assert not res.unmatched_a and not res.unmatched_b


def test_match_to_ground_truth_tp_miss_false_and_gray():
    m = Matcher(judge=None)
    defects = [
        SeededDefect(
            id="x-d1", description="the divisor is never checked for zero",
            location=Location("f.py", 5, 5), severity=Severity.MAJOR,
            paraphrases=["division by zero is possible when the divisor is zero"],
        ),
        SeededDefect(
            id="x-d2", description="index goes one past the end of the list",
            location=Location("f.py", 20, 20), severity=Severity.MAJOR, paraphrases=[],
        ),
    ]
    findings = [
        _f("f1", "the divisor is never checked for zero", start=5, end=5),      # TP -> d1
        _f("f2", "the function name is not very descriptive", start=8, end=8),  # gray zone
        _f("f3", "wholly unrelated invented hallucination xyz", start=99, end=99),  # false
    ]
    gray = [Location("f.py", 7, 9)]
    gt = m.match_to_ground_truth(findings, defects, gray_zones=gray)
    assert gt.true_positives == {0: "x-d1"}
    assert gt.missed == ["x-d2"]
    assert gt.false_findings == [2]
    assert gt.gray_findings == [1]


# -- gray-zone policies (audit R3-M3) -------------------------------------
def _gray_case():
    """A defect + a gray zone with a note + three leftover findings:
    one that MATCHES the note, one co-located that does NOT, one far away."""
    defects = [SeededDefect(id="g-d1", description="the divisor is never checked for zero",
                            location=Location("f.py", 5, 5), severity=Severity.MAJOR)]
    note = "no thread safety: concurrent calls race on the shared deque"
    findings = [
        _f("f1", "the divisor is never checked for zero", start=5, end=5),                 # TP
        _f("f2", "the method is not thread safe: concurrent calls race on the deque",
           start=12, end=14),                                                              # matches note
        _f("f3", "the variable names in this block are unclear", start=12, end=14),         # co-located, no match
        _f("f4", "an unrelated invented hallucination flagged far away", start=99, end=99), # false, outside
    ]
    zone = GrayZone(Location("f.py", 10, 16), note)
    return defects, findings, zone


def test_gray_zone_semantic_gate_requires_note_match():
    """Semantic policy excuses only a finding whose claim matches the zone note; a
    co-located finding that does NOT match the note is a false finding (closes the
    positional leak)."""
    defects, findings, zone = _gray_case()
    m = Matcher(judge=None, gray_policy="semantic")
    gt = m.match_to_ground_truth(findings, defects, gray_zones=[zone])
    assert gt.true_positives == {0: "g-d1"}
    assert gt.gray_findings == [1]                 # note-matching finding excused
    assert set(gt.false_findings) == {2, 3}        # co-located-but-unmatched f3 is NOT excused


def test_gray_zone_positional_excuses_colocated_regardless_of_claim():
    """Legacy positional policy excuses ANY finding overlapping the zone region —
    including the unrelated co-located f3 (the leak the semantic gate closes)."""
    defects, findings, zone = _gray_case()
    m = Matcher(judge=None, gray_policy="positional")
    gt = m.match_to_ground_truth(findings, defects, gray_zones=[zone])
    assert set(gt.gray_findings) == {1, 2}         # both co-located findings excused
    assert gt.false_findings == [3]


def test_gray_zone_none_policy_excuses_nothing():
    """The maximally-punitive bound: no gray-zone excusal, every would-be-gray
    finding is counted as a false finding."""
    defects, findings, zone = _gray_case()
    m = Matcher(judge=None, gray_policy="none")
    gt = m.match_to_ground_truth(findings, defects, gray_zones=[zone])
    assert gt.gray_findings == []
    assert set(gt.false_findings) == {1, 2, 3}


def test_gray_zone_semantic_gate_closes_unlocalized_leak():
    """An UNLOCALIZED finding (no line numbers) in a gray unit is excused positionally
    for any claim, but under the semantic gate only if its claim matches the note."""
    defects = [SeededDefect(id="g-d1", description="the divisor is never checked for zero",
                            location=Location("f.py", 5, 5), severity=Severity.MAJOR)]
    note = "no thread safety: concurrent calls race on the shared deque"
    zone = GrayZone(Location("f.py", None, None), note)  # unit-level gray zone
    unloc_match = Finding(id="u1", claim="not thread safe: concurrent calls race on the deque",
                          location=Location("f.py"))
    unloc_nomatch = Finding(id="u2", claim="the code could use more comments",
                            location=Location("f.py"))
    m_pos = Matcher(judge=None, gray_policy="positional")
    m_sem = Matcher(judge=None, gray_policy="semantic")
    # positional: both unlocalized findings excused merely for being in the unit
    gp = m_pos.match_to_ground_truth([unloc_match, unloc_nomatch], defects, gray_zones=[zone])
    assert set(gp.gray_findings) == {0, 1}
    # semantic: only the note-matching one is excused; the vague one is a false finding
    gs = m_sem.match_to_ground_truth([unloc_match, unloc_nomatch], defects, gray_zones=[zone])
    assert gs.gray_findings == [0]
    assert gs.false_findings == [1]


# -- max-cardinality assignment (audit #1/#2/#3) --------------------------
def test_max_cardinality_helper_recovers_stranded_match():
    # Audit #1 geometry: finding 0 reaches defect 0 (.90) AND defect 1 (.80);
    # finding 1 reaches ONLY defect 0 (.85). Greedy binds the highest edge (0-d0)
    # first, stranding finding 1 and leaving defect 1 unmatched (cardinality 1).
    # A maximum-cardinality matching augments 0 onto d1 so 1 can take d0 (card 2).
    adj = {0: [(0.90, 0), (0.80, 1)], 1: [(0.85, 0)]}
    order = sorted(adj, key=lambda i: (-adj[i][0][0], i))
    match = _max_cardinality_matching(adj, order)
    assert set(match) == {0, 1}          # both defects matched
    assert match == {1: 0, 0: 1}         # d0<-f1, d1<-f0 (the augmenting solution)


def _wl_judge(same_pairs):
    """A judge that returns SAME iff (finding_claim, defect_text) is whitelisted."""
    def judge(ta, la, tb, lb):
        return (ta, tb) in same_pairs
    return judge


# The audit-#1 geometry rendered through the real matcher: f0 is lexically identical
# to d0 (lexical-high, score 1.0) and judge-matched to d1; f1 is judge-matched to d0
# only. Greedy would take f0-d0 and miss d1 (recall 1/2, f1 wrongly excused as a
# "duplicate"); max-cardinality recovers both (recall 2/2).
_D0 = "the loop upper bound is off by one"
_D1 = "the divisor is never checked for zero"
_F1 = "loop bound wrong"
_AUG_DEFECTS = [
    SeededDefect(id="x-d0", description=_D0, location=Location("f.py"),
                 severity=Severity.MAJOR, paraphrases=[]),
    SeededDefect(id="x-d1", description=_D1, location=Location("f.py"),
                 severity=Severity.MAJOR, paraphrases=[]),
]
_AUG_FINDINGS = [_f("f0", _D0), _f("f1", _F1)]
_AUG_JUDGE_PAIRS = {(_D0, _D1), (_F1, _D0)}  # f0~d1 and f1~d0 (f0~d0 is lexical-high)


def test_match_to_ground_truth_augmenting_recovers_recall():
    m = Matcher(judge=_wl_judge(_AUG_JUDGE_PAIRS))
    gt = m.match_to_ground_truth(_AUG_FINDINGS, _AUG_DEFECTS)
    # both defects found, both findings are true positives, nothing stranded
    assert gt.missed == []
    assert set(gt.true_positives.values()) == {"x-d0", "x-d1"}
    assert gt.false_findings == [] and gt.gray_findings == []


def test_duplicate_excused_only_when_its_defect_is_claimed():
    # Audit #2: a leftover finding is excused as a duplicate ONLY if the defect it
    # matches is already claimed. Here two findings both match d0 (and only d0): one
    # is the TP, the other is a genuine duplicate (excused, not a hallucination).
    m = Matcher(judge=_wl_judge({(_F1, _D0)}))
    findings = [_f("f0", _D0), _f("f1", _F1)]  # f0 lexical-high to d0; f1 judge-SAME to d0
    defects = [_AUG_DEFECTS[0]]                 # only d0 exists
    gt = m.match_to_ground_truth(findings, defects)
    assert set(gt.true_positives.values()) == {"x-d0"}   # exactly one TP
    assert len(gt.true_positives) == 1
    assert gt.false_findings == [] and gt.gray_findings == []  # the other is a duplicate, excused
    assert gt.missed == []


def test_ground_truth_warm_cache_equals_cold(tmp_path):
    # Audit #3: a warm (cache-replayed) run must produce the SAME assignment as the
    # cold run that built the cache. The old code scored cache hits with opposite
    # signs in the two assignment paths, so a warm re-run could tie-break to a
    # different matching. With the unified score + max-cardinality, warm == cold.
    m = Matcher(judge=_wl_judge(_AUG_JUDGE_PAIRS))
    cold = m.match_to_ground_truth(_AUG_FINDINGS, _AUG_DEFECTS)   # populates the cache
    warm = m.match_to_ground_truth(_AUG_FINDINGS, _AUG_DEFECTS)   # all edges now cache hits
    assert warm.true_positives == cold.true_positives
    assert warm.missed == cold.missed
    assert warm.false_findings == cold.false_findings
    assert warm.gray_findings == cold.gray_findings
    assert cold.missed == []  # and it's the CORRECT assignment, not a degenerate one


# -- validation -----------------------------------------------------------
def _mini_corpus():
    d1 = SeededDefect(id="c-0001-d1", description="off by one in the upper loop bound",
                      location=Location("a.py", 4, 4), severity=Severity.MAJOR,
                      paraphrases=["the loop runs one iteration too many", "upper bound is too large by one"])
    d2 = SeededDefect(id="c-0001-d2", description="the return value ignores the remainder",
                      location=Location("a.py", 9, 9), severity=Severity.MINOR,
                      paraphrases=["remainder is dropped from the result"])
    d3 = SeededDefect(id="p-0001-d1", description="the reported total does not match the sum of parts",
                      location=Location("sec1", 3, 3), severity=Severity.MAJOR,
                      paraphrases=["the components do not add up to the stated total"])
    it1 = SimpleNamespace(id="c-0001", defects=[d1, d2])
    it2 = SimpleNamespace(id="p-0001", defects=[d3])
    return [it1, it2]


def test_build_gold_labels_and_balance():
    pairs = build_gold_from_corpus(_mini_corpus(), seed=1)
    assert pairs, "should produce pairs"
    pos = [p for p in pairs if p.label]
    neg = [p for p in pairs if not p.label]
    # positives are within-defect paraphrase pairs; all share text meaning
    assert all(p.source == "oracle:paraphrase" for p in pos)
    # negatives are cross-defect
    assert all(p.source.startswith("oracle:cross-defect") for p in neg)
    assert pos and neg


def test_evaluate_and_self_agreement_deterministic():
    pairs = build_gold_from_corpus(_mini_corpus(), seed=1)
    m = Matcher(judge=None)
    report, methods = evaluate(m, pairs, use_cache=False)
    assert report.n == len(pairs)
    assert 0.0 <= report.precision <= 1.0 and 0.0 <= report.recall <= 1.0
    # deterministic matcher never flips
    agree = self_agreement(m, pairs, runs=3, use_cache=False)
    assert agree["flip_rate"] == 0.0 and agree["self_agreement"] == 1.0


def test_cohen_kappa_known_value():
    a = [True, True, False, False]
    b = [True, False, False, False]
    assert cohen_kappa(a, b) == pytest.approx(0.5)
    assert cohen_kappa([True, False], [True, False]) == pytest.approx(1.0)


def test_threshold_sensitivity_grid():
    pairs = build_gold_from_corpus(_mini_corpus(), seed=1)
    rows = threshold_sensitivity(pairs, tau_mid_grid=(0.35, 0.42, 0.50))
    assert len(rows) == 3
    assert all("tau_mid" in r and "precision" in r and "recall" in r for r in rows)
