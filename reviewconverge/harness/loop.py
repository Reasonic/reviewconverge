"""The iterative-review loop (M2).

Runs an N-round review over a **fixed** artifact — the artifact is never edited
between rounds, so this measures whether the *review* (the finding-set) converges,
not whether a repair converges. Each round the reviewer produces prose, the
extractor turns it into ``Finding`` records, and the per-round finding-set is
logged into a ``RunTrajectory`` (the object the M3 metric suite consumes).

Determinism is not sought in the loop: loop models run at deployment-realistic
defaults (no ``temperature``/``top_p`` — current models reject them), because
suppressing sampling variance would mask the churn we are measuring. Reproducibility
comes from the logged trajectory + pinned model ids + frozen prompts, and from
reporting regime *rates* over repeated runs (PLANS §4.3a.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..schema import Finding, RoundFindingSet, RunTrajectory
from .extractor import FindingExtractor
from .ledger import parse_retirements, split_sections, update_ledger
from .prompts import (
    HARNESS_PROMPT_VERSION,
    REVIEW_SYSTEM_PROMPT,
    build_ledger_review_user_prompt,
    build_review_user_prompt,
)

MAX_ROUNDS = 8  # hard cap; the multiplier explodes otherwise (PLANS §9)


@dataclass
class LoopConfig:
    """One loop configuration.

    Attributes:
        config_id: stable id for this configuration (goes into the trajectory).
        rounds: number of review rounds (default 6, capped at :data:`MAX_ROUNDS`).
        memory: if True, each round is shown the previous round's finding-set and
            asked to re-review; if False, every round reviews the artifact cold.
        panel_size: reviewers per round. 1 = single-reviewer; >1 = a
            self-consistency panel whose findings are unioned before extraction.
        ledger: monotone evidence-ledger arm (M4, Arm 1). Findings persist by
            default and leave only via explicit, grounded retirement. Implies
            memory; single-reviewer only (the arm is defined against the
            single-reviewer memory baseline).
        grounded_retire: only meaningful with ``ledger``. True (default) = the full
            monotone ledger (retire only with stated grounds). False = the
            **structured-memory control arm**: identical prompt + verbatim
            carry-forward, but retirement happens on the model's say-so (no grounds
            gate). full-ledger minus structured-memory isolates the grounded-
            retirement mechanism from the shared prompt/plumbing (M4 confound audit).
    """

    config_id: str
    rounds: int = 6
    memory: bool = True
    panel_size: int = 1
    ledger: bool = False
    grounded_retire: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.rounds <= MAX_ROUNDS:
            raise ValueError(f"rounds must be in 1..{MAX_ROUNDS}, got {self.rounds}")
        if self.panel_size < 1:
            raise ValueError("panel_size must be >= 1")
        if self.ledger:
            if self.panel_size != 1:
                raise ValueError("ledger arm is single-reviewer only (panel_size must be 1)")
            self.memory = True  # the ledger is a memory discipline; carry prior state


@dataclass
class LoopResult:
    """A finished loop run: the trajectory plus provenance for release."""

    trajectory: RunTrajectory
    transcripts: list[list[str]] = field(default_factory=list)  # raw reviewer text per round
    reviewer_calls: int = 0
    extractor_calls: int = 0

    def to_dict(self) -> dict:
        return {
            "trajectory": self.trajectory.to_dict(),
            "transcripts": self.transcripts,
            "reviewer_calls": self.reviewer_calls,
            "extractor_calls": self.extractor_calls,
            "prompt_version": HARNESS_PROMPT_VERSION,
        }


class ReviewLoop:
    """Configurable N-round review loop over a fixed artifact."""

    def __init__(self, reviewer_client, extractor: FindingExtractor, config: LoopConfig) -> None:
        self.reviewer = reviewer_client
        self.extractor = extractor
        self.config = config
        self.reviewer_calls = 0

    def _review_once(self, artifact_text: str, artifact_type: str,
                     prior: Optional[list[Finding]]) -> str:
        user = build_review_user_prompt(artifact_text, artifact_type, prior)
        self.reviewer_calls += 1
        return self.reviewer.complete(REVIEW_SYSTEM_PROMPT, user)

    @staticmethod
    def _renumber(findings: list[Finding], r: int) -> list[Finding]:
        """Stamp a round's finding-set with the ``r{r}-f{i}`` id scheme (ids are a
        per-round display handle; cross-round identity is decided by the matcher on
        content, so re-stamping carried-forward ledger items is safe)."""
        return [
            Finding(id=f"r{r}-f{i}", claim=f.claim, location=f.location,
                    severity=f.severity, evidence=f.evidence, raw=f.raw)
            for i, f in enumerate(findings)
        ]

    def _run_ledger(self, artifact_text, artifact_type, r, ledger):
        """One ledger round (r>0): render the ledger, take the reviewer's grounded
        retirements + new issues, and apply the monotone update. Returns the new
        ledger (already re-stamped for round ``r``)."""
        user = build_ledger_review_user_prompt(artifact_text, artifact_type, ledger)
        self.reviewer_calls += 1
        text = self.reviewer.complete(REVIEW_SYSTEM_PROMPT, user)
        retire_block, new_block = split_sections(text)
        min_words = 2 if self.config.grounded_retire else 0
        retired = parse_retirements(retire_block, len(ledger), min_reason_words=min_words)
        new_findings = self.extractor.extract(artifact_text, new_block, r)
        updated = update_ledger(ledger, retired, new_findings)
        return self._renumber(updated, r), [text]

    def run(
        self,
        artifact_text: str,
        artifact_type: str,
        artifact_id: str,
        *,
        run_id: str,
        model_id: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> LoopResult:
        model_id = model_id or getattr(self.reviewer, "model", "unknown")
        rounds: list[RoundFindingSet] = []
        transcripts: list[list[str]] = []
        prior: Optional[list[Finding]] = None

        for r in range(self.config.rounds):
            if self.config.ledger and r > 0:
                # Ledger arm: r>0 is a grounded retire/add update over the carried
                # ledger (round 0 is an ordinary cold review that seeds it).
                findings, round_texts = self._run_ledger(
                    artifact_text, artifact_type, r, prior or [])
            else:
                mem = prior if self.config.memory else None
                round_texts = [
                    self._review_once(artifact_text, artifact_type, mem)
                    for _ in range(self.config.panel_size)
                ]
                # Extract each reviewer's prose, union the findings (panel), renumber ids.
                findings = []
                for text in round_texts:
                    for f in self.extractor.extract(artifact_text, text, r):
                        findings.append(f)
                findings = self._renumber(findings, r)
            rounds.append(RoundFindingSet(round_index=r, findings=findings))
            transcripts.append(round_texts)
            prior = findings

        trajectory = RunTrajectory(
            run_id=run_id,
            artifact_id=artifact_id,
            config_id=self.config.config_id,
            model_id=model_id,
            seed=seed,
            rounds=rounds,
        )
        return LoopResult(
            trajectory=trajectory,
            transcripts=transcripts,
            reviewer_calls=self.reviewer_calls,
            extractor_calls=self.extractor.calls,
        )
