"""Frozen, versioned prompts for the iterative-review harness (M2).

Two roles, two prompts, one frozen version:

- **Reviewer** — reads the artifact (and, with memory, the prior round's findings)
  and writes a free-text review listing concrete issues. This mimics a real review
  loop: the model produces prose, not schema.
- **Extractor** — a fixed parser that turns any free-text review into ``Finding``
  records. Keeping it separate is what lets ReviewConverge instrument *any* loop:
  point the extractor at whatever prose your reviewer emits.

Editing any prompt here is a breaking change — bump :data:`HARNESS_PROMPT_VERSION`
and re-run, because every logged trajectory is attributed to it.
"""

from __future__ import annotations

from typing import Optional

from ..schema import Finding

HARNESS_PROMPT_VERSION = "1.1.0"  # 1.1.0: + monotone evidence-ledger arm (M4); reviewer/extractor prompts unchanged

# The artifact is NEVER edited between rounds — the loop reviews a fixed target,
# so this prompt asks only for issues, never for a rewrite.
REVIEW_SYSTEM_PROMPT = (
    "You are a meticulous reviewer. You are given one artifact — a code change, a "
    "short report/paper excerpt, or a configuration/spec — and must find the "
    "concrete problems in it: bugs, logical errors, factual/arithmetic "
    "inconsistencies, misconfigurations, and violated constraints.\n\n"
    "Report each distinct issue as its own numbered item. For each: state the "
    "problem in one sentence, cite where it is (a line number, section, or key), "
    "and give the evidence that makes it a problem. Only report issues you can "
    "justify from the artifact itself. If you find no issues, say so explicitly. "
    "Do NOT rewrite or fix the artifact — only review it."
)


def build_review_user_prompt(
    artifact_text: str,
    artifact_type: str,
    prior_findings: Optional[list[Finding]] = None,
) -> str:
    """Render the reviewer's user turn: the artifact, plus prior findings if memory is on."""
    parts = [f"Artifact type: {artifact_type}", "", "--- ARTIFACT ---", artifact_text, "--- END ARTIFACT ---"]
    if prior_findings:
        parts += ["", "In the previous round you (or another reviewer) reported these issues:"]
        for i, f in enumerate(prior_findings, 1):
            loc = _loc_str(f)
            parts.append(f"  {i}. [{loc}] {f.claim}")
        parts.append(
            "\nRe-review the artifact from scratch. Keep the issues that still hold, "
            "drop any that were mistaken, and add any you missed. Report your full "
            "current list of issues."
        )
    else:
        parts.append("\nReport all issues you find.")
    return "\n".join(parts)


# -- Monotone evidence-ledger arm (M4, Arm 1) -----------------------------------
# The ledger config replaces the memory config's *free* re-review with a structural
# discipline: a finding persists by default and can leave the set ONLY via an
# explicit, grounded retirement. The reviewer's turn is split into two labelled
# sections so the loop can enforce that discipline in code (see harness/ledger.py):
# items the reviewer does not explicitly, grounded-ly retire remain in the ledger.
LEDGER_RETIRE_HEADER = "RETIRE"
LEDGER_NEW_HEADER = "NEW ISSUES"


def build_ledger_review_user_prompt(
    artifact_text: str,
    artifact_type: str,
    ledger: list[Finding],
) -> str:
    """Render the reviewer's user turn for the monotone evidence-ledger arm.

    Shows the artifact and the running ledger (numbered), then asks for exactly two
    labelled sections — ``RETIRE`` (grounded retirements, by ledger number) and
    ``NEW ISSUES`` (additions). The loop keeps every un-retired item, so removing a
    finding requires the reviewer to actively state why it is not a real problem.
    """
    parts = [
        f"Artifact type: {artifact_type}",
        "",
        "--- ARTIFACT ---",
        artifact_text,
        "--- END ARTIFACT ---",
        "",
        "A running ledger of issues reported so far:",
    ]
    if ledger:
        for i, f in enumerate(ledger, 1):
            parts.append(f"  {i}. [{_loc_str(f)}] {f.claim}")
    else:
        parts.append("  (empty)")
    parts.append(
        "\nRe-examine each ledger item against the artifact, then update the ledger "
        "under these two headers, exactly:\n\n"
        f"{LEDGER_RETIRE_HEADER}:\n"
        "  For every ledger item you can now show is NOT a real problem, write one\n"
        '  line "item <number>: <specific reason, grounded in the artifact, that it\n'
        '  is not a real issue>". Retire an item ONLY with a concrete reason. Any\n'
        "  item you do not list here stays in the ledger. Write \"none\" if you\n"
        "  retire nothing.\n\n"
        f"{LEDGER_NEW_HEADER}:\n"
        "  List any additional distinct problems not already in the ledger. Number\n"
        "  each, cite where it is, and give the evidence. Write \"none\" if there are\n"
        "  none."
    )
    return "\n".join(parts)


# The extractor never invents issues — it only structures what the review states.
EXTRACTOR_SYSTEM_PROMPT = (
    "You convert a free-text review into a structured list of findings. You are "
    "given the reviewed artifact and the review text. Output a JSON array; each "
    "element is one distinct issue the review claims, with fields:\n"
    '  "claim": one-sentence statement of the issue,\n'
    '  "unit": the file, section, or key it refers to (a string; "" if none),\n'
    '  "start": starting line number if the review gives one (integer or null),\n'
    '  "end": ending line number (integer or null),\n'
    '  "severity": one of "info","minor","major","critical" (best guess),\n'
    '  "evidence": the grounding the review offered (string; "" if none).\n\n'
    "Do NOT add issues the review does not make, do NOT merge distinct issues, and "
    "do NOT drop any. If the review reports no issues, output []. Output ONLY the "
    "JSON array, no prose."
)


def build_extractor_user_prompt(artifact_text: str, review_text: str) -> str:
    return (
        f"--- ARTIFACT ---\n{artifact_text}\n--- END ARTIFACT ---\n\n"
        f"--- REVIEW ---\n{review_text}\n--- END REVIEW ---\n\n"
        "Return the JSON array of findings."
    )


def _loc_str(f: Finding) -> str:
    if f.location is None:
        return "unlocalized"
    loc = f.location
    span = ""
    if loc.start is not None:
        span = f":{loc.start}" + (f"-{loc.end}" if loc.end is not None and loc.end != loc.start else "")
    return f"{loc.unit}{span}"
