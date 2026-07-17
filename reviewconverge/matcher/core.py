"""The finding-equivalence matcher (M1b) — hybrid pipeline over the schema.

Decides whether two findings are "the same issue", the judgment every downstream
metric rests on. The pipeline (PLANS §4.3a.4):

1. **Decision cache** — if this content-pair was decided before, replay it.
2. **Deterministic first pass** — location + lexical signals resolve the clear
   pairs (near-identical wording ⇒ same; textually dissimilar *and* disjoint
   location ⇒ different) with no model call.
3. **LLM judge on the ambiguous remainder** — a pluggable, family-rotated judge
   (family ≠ loop, PLANS §4.3a.1) arbitrates the band, with optional k-call
   majority vote for robustness. Absent a judge, a deterministic lexical
   fallback keeps the matcher fully runnable offline (used for the cheap
   bootstrap validation; the LLM judge closes the semantic-paraphrase gap).

Every verdict is cached by content fingerprint, so repeat runs are identical by
construction. The matcher exposes two entry points: :meth:`Matcher.match` (finding
set vs finding set, across rounds) and :meth:`Matcher.match_to_ground_truth`
(findings vs seeded defects, for correctness + false-finding metrics).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from ..schema import Finding, Location, SeededDefect
from .cache import DecisionCache, finding_fingerprint
from .similarity import (
    LocationCompat,
    location_compatibility,
    symmetric_similarity,
    text_similarity,
)

# A judge answers one question: are these two claims the same issue? It receives
# both claim texts and their (optional) locations. Implementations wrap a rotated
# frontier model; the return is a plain bool so judges are trivially swappable.
Judge = Callable[[str, Optional[Location], str, Optional[Location]], bool]


class JudgeProtocol(Protocol):  # documentation of the Judge contract
    def __call__(
        self,
        text_a: str,
        loc_a: Optional[Location],
        text_b: str,
        loc_b: Optional[Location],
    ) -> bool: ...


@dataclass(frozen=True)
class MatchDecision:
    """Why a pair was called same/different — full provenance for auditing."""

    same: bool
    method: str  # cache | anchor-disjoint | lexical-high | llm | lexical-fallback
    score: float
    votes: Optional[tuple[bool, ...]] = None  # per-call judge votes, if judged


@dataclass
class MatchResult:
    """A bipartite matching between two finding sets (indices into each list)."""

    matched: list[tuple[int, int]] = field(default_factory=list)  # (a_idx, b_idx)
    unmatched_a: list[int] = field(default_factory=list)
    unmatched_b: list[int] = field(default_factory=list)


@dataclass
class GroundTruthMatch:
    """Findings scored against the frozen oracle for one artifact.

    Attributes:
        true_positives: finding index -> matched seeded-defect id.
        missed: seeded-defect ids no finding matched (recall misses).
        false_findings: finding indices matching no defect and not in a
            gray-zone region (the hallucinations M3 counts).
        gray_findings: finding indices matching no defect but falling inside a
            ``known_gray_zone`` region — excluded from the false-finding rate
            (neither true nor false), per the gray-zone policy.
    """

    true_positives: dict[int, str] = field(default_factory=dict)
    missed: list[str] = field(default_factory=list)
    false_findings: list[int] = field(default_factory=list)
    gray_findings: list[int] = field(default_factory=list)


@dataclass
class GrayZone:
    """A declared gray-zone region *with its describing note*.

    The note is what makes a semantic gate possible (``gray_policy="semantic"``):
    a finding is excused only if it actually *reports the gray-zone observation*,
    not merely because it happens to sit in the same unit (audit R3-M3). Passing a
    bare :class:`Location` (no note) keeps the legacy positional behaviour.
    """

    location: Location
    note: str = ""


def _zone_location(z) -> Location:
    return z.location if isinstance(z, GrayZone) else z


def _in_gray_zone(loc: Optional[Location], zones: list) -> bool:
    """Positional-only test: does a finding's location fall inside any gray region?

    This is the *legacy* policy (``gray_policy="positional"``). Its known weakness
    (audit R3-M3): an **unlocalized** finding in a unit that has a gray zone is
    excused for *any* claim, so a vague hallucination in that unit escapes the
    false-finding count. The semantic policy (:meth:`Matcher._gray_zone_hit`) closes
    that by also requiring the finding's claim to match the zone note.
    """
    if loc is None or not zones:
        return False
    for z in zones:
        zl = _zone_location(z)
        if zl.unit != loc.unit:
            continue
        if zl.start is None or zl.end is None or loc.start is None or loc.end is None:
            return True  # unit-level gray zone, or unlocalized finding in that unit
        if loc.start <= zl.end and zl.start <= loc.end:
            return True
    return False


# A cache hit records only a *decided-SAME* verdict, not the original similarity
# score (the cache stores a bool, not the float). When such an edge re-enters the
# assignment we score it with this constant so warm (cached) and cold runs order
# edges consistently — the earlier code used +1.0 in one assignment path and -1.0
# in the other (audit finding #3), which made a warm re-run tie-break differently
# from the cold run that built the cache. A decided SAME is a confident SAME, so a
# high constant is the natural choice; with the max-cardinality matching below the
# *cardinality* (the recall-relevant quantity) is invariant to the tie-break anyway.
_CACHE_HIT_SCORE = 1.0


def _max_cardinality_matching(
    adj: dict[int, list[tuple[float, int]]],
    order: list[int],
) -> dict[int, int]:
    """Maximum-cardinality bipartite matching via Kuhn's augmenting paths.

    Greedy "bind the highest-score edge first" is *not* a maximum matching: it can
    strand a low-degree finding whose only defect was taken by a higher-degree
    finding that had an alternative, leaving a real defect spuriously "missed" and
    deflating recall (audit finding #1). Kuhn's algorithm is optimal in cardinality
    and needs no third-party solver.

    Args:
        adj: ``left_vertex -> [(score, right_vertex), ...]``, each adjacency list
            pre-sorted by score **descending** so that, when more than one
            augmenting choice exists, the higher-confidence edge is preferred. This
            weight-leaning tie-break makes the assignment deterministic and sensible;
            it does not affect the matching *size*, which is what recall counts.
        order: the left vertices to seed, in a deterministic order.

    Returns:
        ``{right_vertex: left_vertex}`` for the matched pairs.
    """
    match_r: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for _score, j in adj.get(i, ()):  # high score first
            if j in seen:
                continue
            seen.add(j)
            if j not in match_r or augment(match_r[j], seen):
                match_r[j] = i
                return True
        return False

    for i in order:
        augment(i, set())
    return match_r


class Matcher:
    """Hybrid, cache-backed finding-equivalence matcher.

    Args:
        judge: optional LLM judge for the ambiguous band. If ``None``, a
            deterministic lexical fallback is used (offline-safe).
        cache: shared :class:`DecisionCache` (created empty if omitted).
        tau_high: similarity at/above which a non-disjoint pair is *same* with no
            model call.
        tau_low: similarity at/below which a *disjoint*-location pair is
            *different* with no model call.
        tau_mid: lexical-fallback decision boundary when no judge is present.
        vote_k: number of judge calls per band pair; the majority wins (odd
            values recommended). ``1`` = single call.
    """

    def __init__(
        self,
        judge: Optional[Judge] = None,
        cache: Optional[DecisionCache] = None,
        *,
        tau_high: float = 0.60,
        tau_low: float = 0.25,
        tau_mid: float = 0.42,
        vote_k: int = 1,
        gray_policy: str = "positional",
        gray_note_tau: float = 0.18,
    ) -> None:
        self.judge = judge
        self.cache = cache if cache is not None else DecisionCache()
        self.tau_high = tau_high
        self.tau_low = tau_low
        self.tau_mid = tau_mid
        self.vote_k = vote_k
        # Gray-zone excusal policy (audit R3-M3):
        #   "positional" — legacy: any finding overlapping/in-unit a gray zone (default,
        #                  preserves the frozen cache + tests);
        #   "semantic"   — a finding is gray only if its claim matches a zone *note*
        #                  (lexically, at/above ``gray_note_tau``) — and, when the
        #                  finding is localized, also overlaps that zone's region;
        #   "none"       — no gray-zone excusal at all (every would-be-gray finding is
        #                  counted as a false finding — the maximally punitive bound).
        self.gray_policy = gray_policy
        self.gray_note_tau = gray_note_tau
        self.judge_calls = 0

    def _gray_zone_hit(self, f: Finding, zones: list) -> bool:
        """Is finding ``f`` excused as a gray-zone observation under ``gray_policy``?"""
        if not zones or self.gray_policy == "none":
            return False
        if self.gray_policy == "positional":
            return _in_gray_zone(f.location, zones)
        # semantic: the finding must *report* the observation, not merely co-locate.
        claim = f.claim or ""
        loc = f.location
        localized = loc is not None and loc.start is not None
        for z in zones:
            note = z.note if isinstance(z, GrayZone) else ""
            if not note or symmetric_similarity(claim, note) < self.gray_note_tau:
                continue  # claim does not match this zone's observation
            if localized:
                zl = _zone_location(z)
                if zl.start is None or zl.end is None:
                    return True  # unit-level zone, note matched
                loc_end = loc.end if loc.end is not None else loc.start  # start-only finding = point
                if loc.unit == zl.unit and loc.start <= zl.end and zl.start <= loc_end:
                    return True
                continue  # note matched but a *different* region — not this zone
            return True  # unlocalized finding whose claim matches a note → gray
        return False

    # -- single pair ------------------------------------------------------
    def decide_pair(
        self,
        text_a: str,
        loc_a: Optional[Location],
        text_b: str,
        loc_b: Optional[Location],
        *,
        use_cache: bool = True,
    ) -> MatchDecision:
        """Decide one pair via cache → deterministic pass → judge/fallback."""
        fp_a = finding_fingerprint(text_a, loc_a)
        fp_b = finding_fingerprint(text_b, loc_b)
        if use_cache:
            cached = self.cache.get(fp_a, fp_b)
            if cached is not None:
                return MatchDecision(same=cached, method="cache", score=float("nan"))

        sim = text_similarity(text_a, text_b)
        loc = location_compatibility(loc_a, loc_b)

        # Deterministic first pass.
        if loc == LocationCompat.DISJOINT and sim <= self.tau_low:
            return self._finalize(fp_a, fp_b, False, "anchor-disjoint", sim, use_cache)
        # lexical-high auto-SAME requires a *symmetric* high score, not just the
        # asymmetric overlap coefficient — otherwise a terse finding that is a mere
        # token-subset of a longer defect would bypass the judge (audit #6). A
        # subset-only-high pair falls through to the judge/fallback below.
        if (
            loc != LocationCompat.DISJOINT
            and sim >= self.tau_high
            and symmetric_similarity(text_a, text_b) >= self.tau_high
        ):
            return self._finalize(fp_a, fp_b, True, "lexical-high", sim, use_cache)

        # Ambiguous band → judge (majority vote) or deterministic fallback.
        if self.judge is not None:
            # Prefer decide() so we learn whether the pair was actually DECIDED. A
            # judge that exposes only __call__ (e.g. RuleJudge) always decides.
            decide = getattr(self.judge, "decide", None)
            if decide is not None:
                results = [decide(text_a, loc_a, text_b, loc_b) for _ in range(max(1, self.vote_k))]
                votes = tuple(bool(v) for v, _ in results)
                decided = all(d for _, d in results)
            else:
                votes = tuple(bool(self.judge(text_a, loc_a, text_b, loc_b))
                              for _ in range(max(1, self.vote_k)))
                decided = True
            self.judge_calls += len(votes)
            same = sum(votes) * 2 > len(votes)
            # An UNDECIDED pair (all retries failed — empty reply / transport error /
            # the judge account running out of credit mid-run) returns the conservative
            # default but MUST NOT be frozen into the cache: caching it would replay a
            # wrong DIFFERENT on every resume. Leave it uncached so a later run (once
            # the outage clears) re-judges it. This makes a judged campaign safely
            # resumable across a quota/credit interruption.
            return self._finalize(fp_a, fp_b, same, "llm", sim, use_cache and decided, votes=votes)

        same = sim >= self.tau_mid
        return self._finalize(fp_a, fp_b, same, "lexical-fallback", sim, use_cache)

    def _finalize(
        self,
        fp_a: str,
        fp_b: str,
        same: bool,
        method: str,
        score: float,
        use_cache: bool,
        votes: Optional[tuple[bool, ...]] = None,
    ) -> MatchDecision:
        if use_cache:
            self.cache.put(fp_a, fp_b, same)
        return MatchDecision(same=same, method=method, score=score, votes=votes)

    def same_finding(self, a: Finding, b: Finding, **kw) -> bool:
        return self.decide_pair(a.claim, a.location, b.claim, b.location, **kw).same

    # -- set vs set (cross-round) ----------------------------------------
    def match(self, a: list[Finding], b: list[Finding]) -> MatchResult:
        """Maximum-cardinality 1:1 bipartite match between two finding sets.

        Scores every cross pair, then computes a maximum-cardinality matching over
        the SAME edges (each finding used at most once). Uses Kuhn augmenting paths
        rather than the old greedy "highest edge first" bind, which was not a maximum
        matching and could leave matchable findings unpaired (audit finding #1).
        """
        adj: dict[int, list[tuple[float, int]]] = defaultdict(list)
        for i, fa in enumerate(a):
            for j, fb in enumerate(b):
                d = self.decide_pair(fa.claim, fa.location, fb.claim, fb.location)
                if d.same:
                    # NaN score ⇒ cache-replayed SAME; score it consistently (#3).
                    s = d.score if d.score == d.score else _CACHE_HIT_SCORE
                    adj[i].append((s, j))
        for i in adj:
            adj[i].sort(reverse=True)  # weight-leaning, deterministic tie-break
        order = sorted(adj, key=lambda i: (-adj[i][0][0], i))  # best-edge first
        match_r = _max_cardinality_matching(adj, order)  # {b_idx: a_idx}
        used_a = set(match_r.values())
        used_b = set(match_r)
        matched = sorted((i, j) for j, i in match_r.items())
        return MatchResult(
            matched=matched,
            unmatched_a=[i for i in range(len(a)) if i not in used_a],
            unmatched_b=[j for j in range(len(b)) if j not in used_b],
        )

    # -- findings vs ground truth ----------------------------------------
    def match_to_ground_truth(
        self,
        findings: list[Finding],
        defects: list[SeededDefect],
        gray_zones: Optional[list[Location]] = None,
        bijective: bool = True,
    ) -> GroundTruthMatch:
        """Score a finding set against the seeded defects for one artifact.

        A finding matches a defect if it is judged the same issue as the defect's
        canonical description *or any of its paraphrases* (the paraphrases exist
        precisely so a matcher must accept them). Matching is a **maximum-cardinality
        1:1 bipartite assignment** (``bijective=True``, the default and the mode the
        canonicalizer uses): each defect is claimed by at most one finding, and the
        assignment maximizes the number of matched pairs. This spreads several
        findings that all match one "magnet" defect onto their next-best defects
        instead of collapsing onto it (the recall-deflation bug fixed 2026-07-06), and
        — via the augmenting-path search — also avoids the greedy failure where a
        low-degree finding is stranded because a higher-scoring finding grabbed its
        only defect while itself having an alternative (audit finding #1).

        Leftover findings are classified in three ways, not two:
          * matched **no** defect at all → a **hallucination** (``false_findings``),
            unless it lands in a ``known_gray_zone`` (``gray_findings``);
          * matched **some** defect but lost the 1:1 assignment → a **duplicate**: a
            second correct finding of an already-found defect. A leftover finding is
            excused as a duplicate **only if every defect it matches is already
            claimed** by the assignment (audit finding #2). Under a maximum-cardinality
            matching that condition holds for every edged-but-unmatched finding (an
            unclaimed reachable defect would be a length-1 augmenting path), so this is
            not a hallucination amnesty — a finding with an edge to a *free* defect is
            matched, not excused. This keeps within-defect duplicates from inflating
            the false-finding count without letting a real miss hide as a "duplicate".

        ``bijective=False`` keeps the older many-to-one behaviour (a defect may be
        claimed by several findings); it is retained only for comparison and is not
        used by the metric pipeline.
        """
        gray_zones = gray_zones or []
        # Adjacency: finding_idx -> [(score, defect_idx), ...] over SAME edges.
        adj: dict[int, list[tuple[float, int]]] = defaultdict(list)
        for i, f in enumerate(findings):
            for k, d in enumerate(defects):
                best = self._finding_vs_defect(f, d)
                if best is not None:
                    adj[i].append((best, k))
        for i in adj:
            adj[i].sort(reverse=True)  # weight-leaning, deterministic tie-break

        tp: dict[int, str] = {}
        used_f: set[int] = set()
        used_d: set[int] = set()
        if bijective:
            order = sorted(adj, key=lambda i: (-adj[i][0][0], i))  # best-edge first
            match_d = _max_cardinality_matching(adj, order)  # {defect_idx: finding_idx}
            for k, i in match_d.items():
                tp[i] = defects[k].id
                used_f.add(i)
                used_d.add(k)
        else:
            # Legacy many-to-one (comparison only): each finding takes its best defect.
            for i in sorted(adj):
                _s, k = adj[i][0]
                tp[i] = defects[k].id
                used_f.add(i)
                used_d.add(k)

        false_findings: list[int] = []
        gray_findings: list[int] = []
        for i, f in enumerate(findings):
            if i in used_f:
                continue
            reachable = adj.get(i)  # defects this finding matched, if any
            # Excuse as a duplicate only when it matched >=1 defect AND every defect
            # it reaches is already claimed (audit #2). Otherwise it is a hallucination.
            if reachable and all(k in used_d for _s, k in reachable):
                continue
            if self._gray_zone_hit(f, gray_zones):
                gray_findings.append(i)
            else:
                false_findings.append(i)

        missed = [d.id for k, d in enumerate(defects) if k not in used_d]
        return GroundTruthMatch(
            true_positives=tp,
            missed=missed,
            false_findings=false_findings,
            gray_findings=gray_findings,
        )

    def _finding_vs_defect(self, f: Finding, d: SeededDefect) -> Optional[float]:
        """Best SAME score of a finding against a defect's description+paraphrases."""
        best: Optional[float] = None
        for cand in (d.description, *d.paraphrases):
            dec = self.decide_pair(f.claim, f.location, cand, d.location)
            if dec.same:
                # cache hit ⇒ NaN score ⇒ score consistently with match() (#3).
                s = dec.score if dec.score == dec.score else _CACHE_HIT_SCORE
                best = s if best is None else max(best, s)
        return best
