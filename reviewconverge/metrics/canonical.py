"""Canonicalize a review trajectory into stable per-round element sets (M3).

Every convergence metric rests on one question the matcher answers: *is this
finding the same issue as that one?* This module turns a ``RunTrajectory`` (raw
per-round finding-sets) into a sequence of sets of **stable element ids**, so the
metric suite can treat convergence as set dynamics.

Two audit constraints from M2 are enforced here:

1. **Judged matcher, not deterministic.** Real reviewer findings have mismatched
   locations and lexical variance; the deterministic pass mis-scores them. Pass a
   :class:`~reviewconverge.matcher.Matcher` configured with an LLM judge.
2. **Recall is scored on the RAW finding set (match-before-dedup), via a 1:1
   assignment.** ``match_to_ground_truth`` (bijective) maps the round's raw findings
   to seeded defects as a greedy 1:1 bipartite match, then the defect id is the
   canonical key for each true element. Matching *before* any dedup is what fixes
   the original over-merge bug (deduping first could merge two findings that hit
   *distinct* defects and drop one). The 1:1 assignment additionally prevents the
   opposite failure — several findings all matching one "magnet" defect collapsing
   onto it and leaving the others scored "missed" (audit 2026-07-06). Findings that
   match a defect but lose the assignment are duplicates (dropped); only genuine
   non-matching findings reach the false path, where cross-round clustering avoids
   double-counting the same hallucination.

Element ids are stable across rounds: a finding that matches seeded defect ``d``
in any round is ``def:<d>``; unmatched (false) findings are clustered across rounds
into ``false:<k>``; gray-zone findings are dropped (neither true nor false).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..schema import Finding, Location, RunTrajectory, SeededDefect


@dataclass
class CanonicalRound:
    round_index: int
    elements: set[str] = field(default_factory=set)


@dataclass
class CanonicalTrajectory:
    """A trajectory as per-round sets of stable element ids, plus a truth map."""

    rounds: list[CanonicalRound]
    defect_ids: list[str]                       # all seeded defects (ground truth)
    element_is_true: dict[str, bool]            # element id -> True if a seeded defect
    reps: dict[str, Finding] = field(default_factory=dict)  # element id -> a representative finding

    def round_sets(self) -> list[set[str]]:
        return [cr.elements for cr in self.rounds]


def cluster_findings(findings: list[Finding], matcher) -> list[Finding]:
    """Greedily dedup a round's findings to one representative per distinct issue."""
    reps: list[Finding] = []
    for f in findings:
        if not any(matcher.same_finding(f, rep) for rep in reps):
            reps.append(f)
    return reps


def canonicalize_trajectory(
    trajectory: RunTrajectory,
    defects: list[SeededDefect],
    matcher,
    gray_zones: Optional[list[Location]] = None,
) -> CanonicalTrajectory:
    """Build the stable-element-set view of a trajectory (see module docstring)."""
    gray_zones = gray_zones or []
    defect_ids = [d.id for d in defects]
    element_is_true: dict[str, bool] = {}
    reps_map: dict[str, Finding] = {}

    false_reps: list[Finding] = []   # representatives for cross-round false clustering
    false_ids: list[str] = []

    out_rounds: list[CanonicalRound] = []
    for rfs in trajectory.rounds:
        # Match the RAW findings via 1:1 assignment (match-before-dedup): fixes the
        # over-merge that dropped true matches AND the magnet-collapse that piled
        # several findings onto one defect. Duplicates (matched-but-unassigned) are
        # neither true elements nor false findings.
        gt = matcher.match_to_ground_truth(rfs.findings, defects, gray_zones)

        elements: set[str] = set()
        for idx, defect_id in gt.true_positives.items():
            eid = f"def:{defect_id}"
            elements.add(eid)
            element_is_true[eid] = True
            reps_map.setdefault(eid, rfs.findings[idx])
        # Dedup only the leftover false findings (within-round), then cluster the
        # same hallucination across rounds.
        false_raw = [rfs.findings[idx] for idx in gt.false_findings]
        for f in cluster_findings(false_raw, matcher):
            fid = None
            for k, frep in enumerate(false_reps):
                if matcher.same_finding(f, frep):
                    fid = false_ids[k]
                    break
            if fid is None:
                fid = f"false:{len(false_reps)}"
                false_reps.append(f)
                false_ids.append(fid)
                reps_map[fid] = f
            elements.add(fid)
            element_is_true[fid] = False
        # gt.gray_findings are intentionally dropped
        out_rounds.append(CanonicalRound(round_index=rfs.round_index, elements=elements))

    return CanonicalTrajectory(
        rounds=out_rounds,
        defect_ids=defect_ids,
        element_is_true=element_is_true,
        reps=reps_map,
    )
