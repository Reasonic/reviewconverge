"""Finding-equivalence matcher (M1b).

The load-bearing component: every metric depends on deciding whether a finding in
round r is "the same" issue as a finding in round r+1, and whether a finding
matches a seeded defect. A hallucinating matcher would invalidate the whole
benchmark, so this module ships *with* its validation.

Public surface:
    - :class:`Matcher` — location-anchored + lexical/LLM-judge hybrid with a
      content-addressed :class:`DecisionCache` for determinism-by-construction.
      ``match(a, b)`` (cross-round) and ``match_to_ground_truth(findings,
      defects, gray_zones)`` (correctness) are the entry points.
    - :mod:`.validation` — gold-set construction from the frozen oracle,
      precision/recall, Cohen's κ, self-agreement/flip-rate, and threshold
      sensitivity (the sub-study in PLANS §4.2).

Determinism note (PLANS §4.3a.4): verdicts do not depend on sampler temperature;
each ``(finding_a, finding_b)`` decision is cached by content and replayed.
"""

from .cache import DecisionCache, finding_fingerprint, pair_key
from .core import (
    GroundTruthMatch,
    Judge,
    MatchDecision,
    Matcher,
    MatchResult,
)
from .judges import (
    JUDGE_PROMPT_VERSION,
    AnthropicClient,
    DeepSeekClient,
    LLMJudge,
    OpenAIClient,
    RuleJudge,
    build_client,
    build_user_prompt,
    model_family,
    parse_verdict,
    rotate_judge_family,
    same_family_clash,
    spec_family,
)
from .similarity import (
    LocationCompat,
    location_compatibility,
    normalize,
    text_similarity,
)

__all__ = [
    "Matcher",
    "MatchDecision",
    "MatchResult",
    "GroundTruthMatch",
    "Judge",
    "DecisionCache",
    "finding_fingerprint",
    "pair_key",
    "text_similarity",
    "location_compatibility",
    "LocationCompat",
    "normalize",
    # judges
    "LLMJudge",
    "RuleJudge",
    "AnthropicClient",
    "OpenAIClient",
    "DeepSeekClient",
    "build_client",
    "build_user_prompt",
    "parse_verdict",
    "model_family",
    "rotate_judge_family",
    "same_family_clash",
    "spec_family",
    "JUDGE_PROMPT_VERSION",
]
