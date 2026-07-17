"""Iterative-review harness (M2).

Runs an N-round review loop over a *fixed* artifact (the artifact is never edited
between rounds — this measures review convergence, not repair), logging the full
finding-set each round into a ``RunTrajectory`` (see ``reviewconverge.schema``).

Public surface:
    - :class:`ReviewLoop` + :class:`LoopConfig` + :class:`LoopResult` — the
      configurable loop (single-reviewer / self-consistency panel; with/without
      round memory), round cap, replayable via the logged trajectory.
    - :class:`FindingExtractor` — the frozen, versioned free-text -> Finding parser
      that lets ReviewConverge instrument an arbitrary review loop.
    - :mod:`.prompts` — the frozen reviewer + extractor prompts
      (:data:`HARNESS_PROMPT_VERSION`).

Loop models run at deployment-realistic defaults (no temperature); reproducibility
is the logged trajectory + pinned ids + frozen prompts (PLANS §4.3a.4). The first
intervention config — the monotone evidence-ledger (M4, Arm 1) — is
``LoopConfig(ledger=True)``; its network-free update logic lives in :mod:`.ledger`.
"""

from .extractor import FindingExtractor
from .ledger import parse_retirements, split_sections, update_ledger
from .loop import MAX_ROUNDS, LoopConfig, LoopResult, ReviewLoop
from .prompts import (
    EXTRACTOR_SYSTEM_PROMPT,
    HARNESS_PROMPT_VERSION,
    REVIEW_SYSTEM_PROMPT,
    build_extractor_user_prompt,
    build_ledger_review_user_prompt,
    build_review_user_prompt,
)

__all__ = [
    "ReviewLoop",
    "LoopConfig",
    "LoopResult",
    "FindingExtractor",
    "MAX_ROUNDS",
    "HARNESS_PROMPT_VERSION",
    "REVIEW_SYSTEM_PROMPT",
    "EXTRACTOR_SYSTEM_PROMPT",
    "build_review_user_prompt",
    "build_ledger_review_user_prompt",
    "build_extractor_user_prompt",
    "split_sections",
    "parse_retirements",
    "update_ledger",
]
