"""Finding-record schema — the interchange format for ReviewConverge.

Every review round emits a *finding-set*: the set of issues the reviewer claims
about the artifact in that round. All ReviewConverge metrics operate on these
records, so this schema is the contract between (a) any review loop being
measured, (b) the finding-equivalence matcher, and (c) the metric suite.

Free-text reviews are parsed into ``Finding`` records by a frozen, versioned
extractor (see ``reviewconverge.harness``); to instrument your own loop, emit
``Finding`` records directly.

This module is deliberately dependency-free (stdlib only) so the schema can be
imported anywhere, including inside a loop being benchmarked.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    """Severity of a claimed finding. Ordinal, low to high."""

    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Location:
    """Where in the artifact a finding is anchored.

    Anchoring is what lets the matcher decide whether two findings across rounds
    refer to the same issue. ``unit`` names the artifact-local addressing scheme
    (e.g. a file path for code, a section id for a paper, a key path for a spec);
    ``start``/``end`` are optional line/char offsets within it.
    """

    unit: str
    start: Optional[int] = None
    end: Optional[int] = None


@dataclass(frozen=True)
class Finding:
    """A single claimed issue in one review round.

    Attributes:
        id: Stable id for this finding *within a run* (assigned at extraction).
        claim: The reviewer's assertion — the canonical statement of the issue.
        location: Where in the artifact the finding is anchored (may be None if
            the reviewer did not localize it; unlocalized findings are handled
            explicitly by the matcher rather than silently dropped).
        severity: Reviewer-assigned severity.
        evidence: The grounding the reviewer offered (quote, reproduction,
            reference). Central to the grounding-gated-admission intervention arm.
        raw: Optional passthrough of the original text/span for provenance.
    """

    id: str
    claim: str
    location: Optional[Location] = None
    severity: Severity = Severity.MINOR
    evidence: Optional[str] = None
    raw: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeededDefect:
    """A ground-truth defect planted in a corpus artifact.

    Ground truth is *constructed*, never LLM-discovered, and frozen before any
    loop runs (see corpus/README.md). ``paraphrases`` seed the matcher gold set.

    Attributes:
        id: Stable, corpus-wide unique defect id (e.g. ``code-0001-d1``).
        description: The canonical one-sentence statement of the issue.
        location: Where the defect lives in the artifact.
        severity: Constructed severity of the seeded defect.
        category: Injection category from the construction taxonomy
            (e.g. ``off-by-one``, ``stat-inconsistency``). Drives the
            per-category metric breakdowns (false-finding rate by kind, etc.).
        paraphrases: 2-3 alternative phrasings of the same issue; these seed the
            matcher gold set (a matcher must call a paraphrase the *same* finding).
    """

    id: str
    description: str
    location: Location
    severity: Severity
    category: Optional[str] = None
    paraphrases: list[str] = field(default_factory=list)


@dataclass
class RoundFindingSet:
    """The full finding-set emitted in one round of a review loop."""

    round_index: int
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class RunTrajectory:
    """The per-round finding-set trajectory for a single review-loop run.

    This is the object the metric suite and regime classifier consume. It also
    carries enough provenance (artifact id, model/config ids, seed) to make every
    reported number reproducible from ``runs/``.
    """

    run_id: str
    artifact_id: str
    config_id: str
    model_id: str
    seed: Optional[int] = None
    rounds: list[RoundFindingSet] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "config_id": self.config_id,
            "model_id": self.model_id,
            "seed": self.seed,
            "rounds": [r.to_dict() for r in self.rounds],
        }


SCHEMA_VERSION = "0.1.0"
