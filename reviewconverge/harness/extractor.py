"""Free-text review -> ``Finding`` records (M2).

A frozen, model-backed parser. The reviewer emits prose; the extractor turns that
prose into the schema every metric consumes. Keeping extraction separate from
reviewing is deliberate: it lets ReviewConverge instrument an arbitrary review
loop by parsing whatever text it produces, and it pins the free-text→schema step
to one versioned prompt rather than baking structure into each reviewer.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..schema import Finding, Location, Severity
from .prompts import EXTRACTOR_SYSTEM_PROMPT, HARNESS_PROMPT_VERSION, build_extractor_user_prompt

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _coerce_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_findings_json(raw: str, round_index: int) -> list[Finding]:
    """Parse the extractor's reply into ``Finding`` records (best-effort, robust)."""
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # Fall back to the first top-level JSON array if there is surrounding prose.
    if not text.startswith("["):
        lo, hi = text.find("["), text.rfind("]")
        if lo != -1 and hi != -1 and hi > lo:
            text = text[lo : hi + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    findings: list[Finding] = []
    for i, rec in enumerate(data):
        if not isinstance(rec, dict):
            continue
        claim = str(rec.get("claim", "")).strip()
        if not claim:
            continue
        unit = str(rec.get("unit", "") or "").strip()
        start = _coerce_int(rec.get("start"))
        end = _coerce_int(rec.get("end"))
        location = Location(unit=unit, start=start, end=end) if unit else None
        sev_raw = str(rec.get("severity", "minor")).strip().lower()
        severity = Severity(sev_raw) if sev_raw in Severity._value2member_map_ else Severity.MINOR
        evidence = str(rec.get("evidence", "") or "").strip() or None
        findings.append(
            Finding(
                id=f"r{round_index}-f{i}",
                claim=claim,
                location=location,
                severity=severity,
                evidence=evidence,
            )
        )
    return findings


class FindingExtractor:
    """Turns a free-text review into ``Finding`` records via a frozen prompt.

    Args:
        client: a model client (``complete(system, user) -> str``).
        max_retries: re-attempts if the reply doesn't parse to a JSON array
            (mirrors the matcher's empty-reply handling for flaky endpoints).
    """

    prompt_version = HARNESS_PROMPT_VERSION

    def __init__(self, client, *, max_retries: int = 2) -> None:
        self.client = client
        self.max_retries = max_retries
        self.calls = 0
        self.parse_failures = 0

    def extract(self, artifact_text: str, review_text: str, round_index: int) -> list[Finding]:
        if not review_text or not review_text.strip():
            return []
        user = build_extractor_user_prompt(artifact_text, review_text)
        for attempt in range(self.max_retries + 1):
            self.calls += 1
            try:
                raw = self.client.complete(EXTRACTOR_SYSTEM_PROMPT, user)
            except Exception:
                continue
            findings = _parse_findings_json(raw, round_index)
            # An empty list is a valid answer ("no issues"); only retry a reply
            # that failed to yield a JSON array at all.
            if findings or raw.strip() in ("[]", "```json\n[]\n```", "```\n[]\n```"):
                return findings
            self.parse_failures += 1
        return []
