"""Monotone evidence-ledger update logic for the ledger intervention arm (M4, Arm 1).

The ledger arm replaces the baseline ``memory`` config's *free* re-review ("keep
what holds, drop what's mistaken") with a structural discipline: a finding stays in
the set **by default** and can leave **only** via an explicit, grounded retirement.
That persistence is enforced here, in code — not left to the model — which is the
whole point of the arm (it targets the memory baseline's two failure modes at once:
silent drop/re-add churn, and silent entrenchment on wrong findings).

This module is deliberately network-free so the ledger mechanics are unit-testable
in isolation; :class:`~reviewconverge.harness.loop.ReviewLoop` orchestrates the
model calls around it.
"""

from __future__ import annotations

import re

from ..matcher.similarity import LocationCompat, location_compatibility, text_similarity
from ..schema import Finding

# Loop-time lexical dedup threshold for *new* findings against the surviving ledger.
# High + location-gated on purpose: it only collapses obvious re-discoveries so the
# ledger prompt doesn't balloon; the M3 metric suite re-dedups with the LLM judge.
DEDUP_SIM = 0.72

_RETIRE_HEADER = re.compile(r"(?im)^[\s#>*-]*RETIRE\b.*$")
_NEW_HEADER = re.compile(r"(?im)^[\s#>*-]*NEW(?:\s+ISSUES)?\b.*$")
# A retirement line: an optional "item"/"#", a 1-3 digit ledger number, a separator,
# then the grounds. The grounds requirement (>= _MIN_REASON_WORDS) is what makes a
# retirement *grounded* — a bare number does not retire anything (monotone default).
_RETIRE_LINE = re.compile(r"(?im)^[\s>*\-]*(?:item\s*)?#?(\d{1,3})\b\s*[:.)\-—]?\s*(.*)$")
_MIN_REASON_WORDS = 2


def split_sections(text: str) -> tuple[str, str]:
    """Split a ledger-round review into ``(retire_block, new_block)``.

    Generic over header ordering: each section runs from its header to the next
    header (or end of text). If the reviewer used no ``RETIRE``/``NEW`` header at
    all, returns ``("", text)`` — the safe monotone fallback: retire nothing, treat
    the whole reply as candidate new issues (the ledger only ever grows, never
    silently drops).
    """
    markers: list[tuple[str, int, int]] = []
    for m in _RETIRE_HEADER.finditer(text):
        markers.append(("retire", m.start(), m.end()))
    for m in _NEW_HEADER.finditer(text):
        markers.append(("new", m.start(), m.end()))
    if not markers:
        return "", text
    markers.sort(key=lambda t: t[1])
    retire_parts: list[str] = []
    new_parts: list[str] = []
    for idx, (kind, _start, end) in enumerate(markers):
        stop = markers[idx + 1][1] if idx + 1 < len(markers) else len(text)
        block = text[end:stop]
        (retire_parts if kind == "retire" else new_parts).append(block)
    return "\n".join(retire_parts), "\n".join(new_parts)


def parse_retirements(retire_block: str, ledger_size: int,
                      min_reason_words: int = _MIN_REASON_WORDS) -> set[int]:
    """Parse a ``RETIRE`` block into a set of 0-based ledger indices to retire.

    ``min_reason_words`` gates retirement on grounds: at the default (2) an item is
    retired only if the reviewer states a reason, so a bare number is ignored (the
    monotone evidence-ledger). Set it to 0 for the **structured-memory control arm**,
    where retirement happens on the model's say-so — this is the one knob that, held
    against the full ledger, isolates the grounded-retirement mechanism from the
    shared prompt structure and verbatim carry-forward.
    """
    retired: set[int] = set()
    for line in retire_block.splitlines():
        m = _RETIRE_LINE.match(line)
        if not m:
            continue
        n = int(m.group(1))
        if not 1 <= n <= ledger_size:
            continue
        if len(m.group(2).split()) < min_reason_words:
            continue
        retired.add(n - 1)
    return retired


def _is_dup(f: Finding, ledger: list[Finding]) -> bool:
    for g in ledger:
        if location_compatibility(f.location, g.location) is LocationCompat.DISJOINT:
            continue
        if text_similarity(f.claim, g.claim) >= DEDUP_SIM:
            return True
    return False


def update_ledger(
    ledger: list[Finding],
    retired_idx: set[int],
    new_findings: list[Finding],
) -> list[Finding]:
    """Apply one round's dispositions: drop the grounded-retired items, append the
    genuinely-new findings (obvious re-discoveries deduped away)."""
    survivors = [f for i, f in enumerate(ledger) if i not in retired_idx]
    out = list(survivors)
    for nf in new_findings:
        if not _is_dup(nf, out):
            out.append(nf)
    return out
