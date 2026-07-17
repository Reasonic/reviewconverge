"""LLM judges for the matcher's ambiguous band (M1b).

The deterministic first pass resolves the clear finding pairs; the residue —
semantically-equivalent claims with little lexical overlap, and lexically-similar
claims that are actually distinct issues — is what an LLM judge is for. This
module supplies:

- a **frozen, versioned prompt** (:data:`JUDGE_PROMPT_VERSION`) so a judged
  verdict is attributable to an exact prompt build;
- a provider-agnostic :class:`ModelClient` and thin **stdlib-``urllib`` adapters**
  for Anthropic / OpenAI / DeepSeek (no SDK dependency; keys read from the
  environment) — the three families the rotation rule picks between;
- :class:`LLMJudge`, which adapts any client to the matcher's ``Judge`` callable;
- the **family-rotation** rule (judge family ≠ loop family, PLANS §4.3a.1); and
- offline judges (:class:`RuleJudge`) so the whole pipeline — including the band —
  runs deterministically in CI and tests without network or spend.

Determinism note: verdicts are pinned by the matcher's decision cache, not by
sampler settings, so no ``temperature`` is sent (current models reject it and it
never guaranteed determinism anyway — PLANS §4.3a.4). The judge's *raw* run-to-run
flip rate is measured (cache off) and reported as a validation number.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Optional, Protocol

from ..schema import Location
from .similarity import content_tokens

JUDGE_PROMPT_VERSION = "1.0.0"

# Frozen system prompt. Editing this is a breaking change — bump the version and
# re-run validation, because every judged verdict is attributed to it.
SYSTEM_PROMPT = (
    "You are an adjudicator for a code/paper/spec review benchmark. You are given "
    "two review findings, each a short claim about the same artifact. Decide "
    "whether they describe the SAME underlying issue or DIFFERENT issues.\n\n"
    "Two findings are the SAME issue if a competent reviewer would consider them "
    "one and the same defect — even if worded very differently, at different "
    "granularity, or citing the fix versus the symptom. They are DIFFERENT if they "
    "point to distinct defects, even when they sit on the same line or in the same "
    "region (proximity is not sameness).\n\n"
    "Be conservative: if the two claims are merely related, adjacent, or share a "
    "location but assert different problems, answer DIFFERENT.\n\n"
    "Answer with exactly one word on the first line: SAME or DIFFERENT. You may add "
    "a brief justification on the following line."
)


class JudgeParseError(ValueError):
    """The model's reply could not be resolved to SAME/DIFFERENT."""


class JudgeConfigError(RuntimeError):
    """A configuration problem (e.g. missing API key) — abort, don't degrade.

    Distinct from a transient transport error: a missing key must fail the whole
    run loudly, never be swallowed into a silent stream of DIFFERENT verdicts.
    """


def build_user_prompt(
    text_a: str, loc_a: Optional[Location], text_b: str, loc_b: Optional[Location]
) -> str:
    """Render one pair into the judge's user message."""

    def loc_str(loc: Optional[Location]) -> str:
        if loc is None:
            return "(unlocalized)"
        span = ""
        if loc.start is not None:
            span = f" lines {loc.start}" + (f"-{loc.end}" if loc.end is not None else "")
        return f"{loc.unit}{span}"

    return (
        f"Finding A [location: {loc_str(loc_a)}]:\n{text_a.strip()}\n\n"
        f"Finding B [location: {loc_str(loc_b)}]:\n{text_b.strip()}\n\n"
        "Same underlying issue?"
    )


_SAME_RE = re.compile(r"\bSAME\b")
_DIFF_RE = re.compile(r"\bDIFFERENT\b")


def parse_verdict(raw: str) -> bool:
    """Resolve a model reply to ``True`` (same) / ``False`` (different).

    Prefers the first line (per the prompt), then falls back to an unambiguous
    single mention anywhere. Raises :class:`JudgeParseError` if the reply names
    both or neither verdict — the caller decides how to treat that (the
    conservative default in :class:`LLMJudge` is DIFFERENT).
    """
    if not raw or not raw.strip():
        raise JudgeParseError("empty reply")
    up = raw.strip().upper()
    first = re.sub(r"^[^A-Z]+", "", up.splitlines()[0].strip())
    if first.startswith("SAME"):
        return True
    if first.startswith("DIFFERENT"):
        return False
    has_same = _SAME_RE.search(up) is not None
    has_diff = _DIFF_RE.search(up) is not None
    if has_same and not has_diff:
        return True
    if has_diff and not has_same:
        return False
    raise JudgeParseError(raw.strip()[:160])


# --------------------------------------------------------------------------- #
# Model clients (stdlib urllib; no SDK dependency)
# --------------------------------------------------------------------------- #
class ModelClient(Protocol):
    """Anything that turns a (system, user) prompt into raw completion text."""

    model: str
    family: str

    def complete(self, system: str, user: str) -> str: ...


# Transient statuses worth retrying (rate limit + gateway/5xx); anything else
# (401/403/400) is a hard error surfaced immediately.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

# Google's OpenAI-compat 429 body carries the wait in a RetryInfo detail, e.g.
# ``"retryDelay": "38s"`` — NOT a Retry-After header. Honor it so a per-minute
# quota is waited out instead of burning the retry budget on too-short backoffs.
_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def _suggested_delay(headers, body: str) -> Optional[float]:
    """Server-suggested retry wait: ``Retry-After`` header (OpenAI/Anthropic) or a
    Google ``retryDelay`` in the body. Returns seconds, or ``None`` if neither."""
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after and retry_after.strip().replace(".", "", 1).isdigit():
        return float(retry_after)
    m = _RETRY_DELAY_RE.search(body or "")
    return float(m.group(1)) if m else None


def _http_post_json(
    url: str, headers: dict, payload: dict, timeout: float = 60.0,
    retries: int = 3, backoff: float = 1.0, max_backoff: float = 45.0,
) -> dict:
    """POST JSON with retry+backoff on transient errors (rate limits, 5xx, network).

    Retrying transient failures is what keeps an expensive concurrent run from
    dying on a single 429; permanent errors (auth, bad request) are raised at once
    so they can't be mistaken for a flaky network. A server-suggested wait
    (``Retry-After`` header or Google ``retryDelay`` body field) is honored when
    present — critical for a per-minute quota, where a fixed short backoff would
    exhaust the retry budget inside one window. All waits are capped at
    ``max_backoff`` so a pathological suggestion can't stall a run indefinitely.
    """
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code in _RETRY_STATUS and attempt < retries:
                suggested = _suggested_delay(e.headers, body)
                delay = (suggested if suggested is not None
                         else backoff * (2 ** attempt)) + random.uniform(0, 0.5)
                time.sleep(min(delay, max_backoff))
                continue
            raise RuntimeError(f"{url} -> HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:  # network / timeout
            if attempt < retries:
                time.sleep(min(backoff * (2 ** attempt) + random.uniform(0, 0.5), max_backoff))
                continue
            raise RuntimeError(f"{url} -> {type(e).__name__}: {e}") from e
    raise RuntimeError(f"{url} -> exhausted {retries} retries")  # unreachable


def _require_key(env_name: str) -> str:
    key = os.environ.get(env_name)
    if not key:
        raise JudgeConfigError(
            f"{env_name} is not set. Export it (or put it in a git-ignored .env) "
            f"before running the LLM judge."
        )
    return key


class AnthropicClient:
    """Claude via the Messages API (stdlib urllib)."""

    family = "anthropic"

    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 64) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        key = _require_key("ANTHROPIC_API_KEY")
        out = _http_post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        parts = [b.get("text", "") for b in out.get("content", []) if b.get("type") == "text"]
        return "".join(parts)


class _OpenAICompatClient:
    """Shared logic for OpenAI and OpenAI-compatible endpoints (DeepSeek)."""

    family = "openai"
    base_url = "https://api.openai.com/v1"
    key_env = "OPENAI_API_KEY"

    def __init__(self, model: str, max_tokens: int = 64,
                 reasoning_effort: Optional[str] = None, timeout: float = 120.0,
                 retries: int = 3, backoff: float = 1.0) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    def complete(self, system: str, user: str) -> str:
        key = _require_key(self.key_env)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": self.max_tokens,
        }
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        out = _http_post_json(
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {key}", "content-type": "application/json"},
            payload,
            timeout=self.timeout,
            retries=self.retries,
            backoff=self.backoff,
        )
        return out["choices"][0]["message"]["content"] or ""


_OPENAI_REASONING_RE = re.compile(r"^(gpt-5|o[134])", re.I)


class OpenAIClient(_OpenAICompatClient):
    family = "openai"
    base_url = "https://api.openai.com/v1"
    key_env = "OPENAI_API_KEY"

    # GPT-5.x / o-series are reasoning models: reasoning tokens count against the
    # completion budget, and even at reasoning_effort='low' an ambiguous band pair
    # occasionally reasons a lot and truncates the answer to empty content
    # (finish_reason=length). max_completion_tokens is a *cap*, not a reservation —
    # you are billed for actual tokens — so a high cap prevents truncation almost
    # for free while effort='low' keeps typical reasoning short. (Non-reasoning
    # OpenAI models reject reasoning_effort, so it's only sent when detected.)
    #
    # CRITICAL: build_client passes its default max_tokens=64 (sized for non-reasoning
    # judges like V4-Pro). For a reasoning model that 64-token budget is spent on hidden
    # reasoning tokens, truncating the verdict to EMPTY content (finish_reason=length) ->
    # unparseable -> undecided — and it bites exactly the hard/ambiguous pairs that reason
    # most. So we FLOOR the cap for reasoning models (same fix as GeminiClient._MIN_TOKENS);
    # the cap is billed on actual tokens, so the floor is ~free. Non-reasoning models keep
    # the caller's cap.
    _MIN_REASONING_TOKENS = 8192

    def __init__(self, model: str = "gpt-5.5", max_tokens: int = 65536,
                 reasoning_effort: Optional[str] = None, timeout: float = 45.0,
                 retries: int = 1) -> None:
        # timeout 45s + retries 1 (were 300s / 3): a legit effort='low' judge verdict
        # returns in <6s, so 45s is a wide margin over real latency. GPT-5.5's endpoint
        # intermittently WEDGES a socket on a sustained batch (connects, never returns) and
        # a stuck process re-wedges on retry (a fresh PROCESS clears it) — so a long timeout
        # x many retries just stalls the concurrency-1 run for tens of minutes. Bounding
        # both makes a wedged pair abort in ~90s (2 decide x 2 http attempts) -> marked
        # undecided (uncached) -> the run continues; the driver restarts on a hard wedge.
        is_reasoning = _OPENAI_REASONING_RE.match(model) is not None
        if reasoning_effort is None and is_reasoning:
            reasoning_effort = "low"
        if is_reasoning:
            max_tokens = max(max_tokens, self._MIN_REASONING_TOKENS)
        super().__init__(model, max_tokens, reasoning_effort, timeout, retries=retries)


class DeepSeekClient(_OpenAICompatClient):
    family = "deepseek"
    base_url = "https://api.deepseek.com/v1"
    key_env = "DEEPSEEK_API_KEY"

    def __init__(self, model: str = "deepseek-v4-pro", max_tokens: int = 64) -> None:
        super().__init__(model, max_tokens)


class GeminiClient(_OpenAICompatClient):
    # Google via its OpenAI-compatibility endpoint — drops into the same client as
    # DeepSeek. Replaces the GPT-5.5 reasoning-arm + judge slot (2026-07-07).
    # Wire details CONFIRMED live 2026-07-07: base_url path OK; the endpoint accepts
    # ``max_completion_tokens`` (this base client sends it); key env GEMINI_API_KEY;
    # exact model string is ``gemini-3.1-pro-preview`` (bare ``gemini-3.1-pro`` 404s).
    # Gemini 3.1 Pro is a *thinking* model — reasoning tokens count against
    # max_completion_tokens, so a 64-token cap truncates the SAME/DIFFERENT verdict
    # to empty (finish_reason=length, content 'DI'). We therefore FLOOR the cap so
    # build_client's default 64 (sized for non-reasoning judges) can't truncate the
    # answer; the cap is billed for actuals (~33 completion tokens observed), so a
    # high floor is ~free. Thinking can be slow -> timeout 300.
    #
    # Rate limits: under sustained concurrent load the endpoint returns 429
    # ("exceeded your current quota") and occasional 503 — a per-minute window, so
    # more retries + a longer backoff (honoring the body's ``retryDelay``) are needed
    # to outlast it. Defaults here (retries=6, backoff=2.0) let a single call wait
    # out one quota window; the RUN should still cap concurrency + pace calls to stay
    # near the tier limit rather than lean on retries alone.
    family = "google"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    key_env = "GEMINI_API_KEY"
    _MIN_TOKENS = 8192

    def __init__(self, model: str = "gemini-3.1-pro-preview", max_tokens: int = 64,
                 timeout: float = 300.0, retries: int = 6, backoff: float = 2.0) -> None:
        super().__init__(model, max(max_tokens, self._MIN_TOKENS), timeout=timeout,
                         retries=retries, backoff=backoff)


# --------------------------------------------------------------------------- #
# Family rotation (judge family != loop family)
# --------------------------------------------------------------------------- #
_FAMILY_PATTERNS = (
    ("anthropic", re.compile(r"claude", re.I)),
    ("openai", re.compile(r"^(gpt|o\d)", re.I)),
    ("deepseek", re.compile(r"deepseek", re.I)),
    ("google", re.compile(r"gemini|gemma", re.I)),
)

# Preference order when picking a judge family. Slate (2026-07-07) = DeepSeek V4-Pro /
# Opus / GPT-5.5 (+ xAI Grok once wired+validated). Gemini was trialed but PARKED
# behind a free-tier 250-req/day wall (GeminiClient is retained for a future paid key),
# so ``google`` is not in the preference. GPT-5.5 is un-retired as the primary recompute
# judge (validated F1 0.9987; the paid OpenAI tier has no daily cap).
_JUDGE_PREFERENCE = ("deepseek", "anthropic", "openai")


def model_family(model_id: str) -> str:
    for fam, pat in _FAMILY_PATTERNS:
        if pat.search(model_id):
            return fam
    return "unknown"


def rotate_judge_family(loop_model_id: str, available: Optional[tuple[str, ...]] = None) -> str:
    """Pick a judge family different from the loop model's family.

    Self-preference bias would inflate match rates — fatal for a paper about
    hallucinated findings — so the judge must never share the loop's family.
    """
    loop_fam = model_family(loop_model_id)
    pool = available or _JUDGE_PREFERENCE
    for fam in pool:
        if fam != loop_fam:
            return fam
    raise ValueError(f"no judge family available that differs from loop family {loop_fam!r}")


# Provider tokens that ``model_family`` (which matches on *model* strings) doesn't
# recognize, so a provider-only judge spec like ``anthropic`` still resolves.
_PROVIDER_FAMILY = {
    "anthropic": "anthropic", "openai": "openai", "deepseek": "deepseek",
    "google": "google", "gemini": "google",
}


def spec_family(judge_spec: str) -> str:
    """Model family for a ``provider:model`` (or bare ``provider``) judge spec.

    Prefers the model part (``deepseek:deepseek-v4-pro`` → ``deepseek``); falls back
    to the provider token for provider-only specs (``anthropic`` → ``anthropic``,
    whose default model ``claude-…`` the pattern would otherwise need). ``unknown``
    if neither resolves.
    """
    provider, _, model = judge_spec.partition(":")
    fam = model_family(model) if model else "unknown"
    if fam != "unknown":
        return fam
    return _PROVIDER_FAMILY.get(provider.strip().lower(), "unknown")


def same_family_clash(judge_spec: str, loop_model_ids: Iterable[str]) -> Optional[str]:
    """Return the shared family if the judge shares a model family with any loop
    model (a PLANS §84 role-separation violation), else ``None``.

    A same-family judge grades its own family's output — a self-preference bias that
    is fatal for a benchmark about hallucinated findings. ``compute_metrics`` refuses
    such a run unless it is explicitly opted into as a disclosed robustness arm. An
    ``unknown`` judge family never clashes (we don't guess).
    """
    jf = spec_family(judge_spec)
    if jf == "unknown":
        return None
    return jf if any(model_family(mid) == jf for mid in loop_model_ids) else None


# --------------------------------------------------------------------------- #
# Judges
# --------------------------------------------------------------------------- #
class LLMJudge:
    """Adapt a :class:`ModelClient` to the matcher's ``Judge`` callable.

    On a parse failure or transport error the judge returns ``False``
    (DIFFERENT) — the conservative choice, since a wrong SAME merges two distinct
    findings and corrupts the trajectory, whereas a wrong DIFFERENT merely leaves
    a pair for a later round. Errors are counted, not silently swallowed.
    """

    def __init__(self, client: ModelClient, *, on_error: bool = False,
                 parse_retries: int = 0, call_delay: float = 0.0) -> None:
        self.client = client
        self.on_error = on_error
        self.parse_retries = parse_retries
        self.call_delay = call_delay  # seconds to pause before each API call
        self.calls = 0
        self.parse_errors = 0
        self.transport_errors = 0
        self.undecided = 0  # pairs where ALL retries failed (outage/quota fingerprint)
        self.family = getattr(client, "family", "unknown")
        self._lock = threading.Lock()  # counters may be touched from worker threads

    def decide(
        self,
        text_a: str,
        loc_a: Optional[Location],
        text_b: str,
        loc_b: Optional[Location],
    ) -> tuple[bool, bool]:
        """Return ``(verdict, decided)``.

        ``decided`` is ``False`` only after ``parse_retries`` re-attempts all fail
        — the verdict is then the conservative ``on_error`` default, but callers
        should NOT cache it: an *undecided* pair must be retried on a later run,
        never frozen into the oracle as a wrong DIFFERENT. Retrying matters because
        reasoning models intermittently return an empty/unparseable reply that a
        fresh call resolves; a transient transport error is likewise re-attempted.
        A missing key raises :class:`JudgeConfigError` (abort, not degrade).
        """
        user = build_user_prompt(text_a, loc_a, text_b, loc_b)
        for attempt in range(self.parse_retries + 1):
            if self.call_delay:
                time.sleep(self.call_delay)  # gentle pacing for a flaky endpoint
            with self._lock:
                self.calls += 1
            try:
                raw = self.client.complete(SYSTEM_PROMPT, user)
            except JudgeConfigError:
                raise
            except Exception:
                with self._lock:
                    self.transport_errors += 1
                continue  # transient -> re-attempt (or fall through to undecided)
            try:
                return parse_verdict(raw), True
            except JudgeParseError:
                with self._lock:
                    self.parse_errors += 1
                continue  # empty/unparseable -> a fresh call usually succeeds
        with self._lock:
            self.undecided += 1  # all retries exhausted: conservative default, uncached
        return self.on_error, False

    def __call__(
        self,
        text_a: str,
        loc_a: Optional[Location],
        text_b: str,
        loc_b: Optional[Location],
    ) -> bool:
        return self.decide(text_a, loc_a, text_b, loc_b)[0]


class RuleJudge:
    """A deterministic, offline stand-in judge (no network, no spend).

    Decides by content-token Jaccard against a threshold. Weaker than an LLM on
    semantic paraphrases, but it lets the *full* pipeline — including the band —
    run in CI and lets tests exercise the judge path without keys.
    """

    family = "rule"

    def __init__(self, threshold: float = 0.34) -> None:
        self.threshold = threshold
        self.calls = 0

    def decide(
        self,
        text_a: str,
        loc_a: Optional[Location],
        text_b: str,
        loc_b: Optional[Location],
    ) -> tuple[bool, bool]:
        return self(text_a, loc_a, text_b, loc_b), True  # always decided (offline)

    def __call__(
        self,
        text_a: str,
        loc_a: Optional[Location],
        text_b: str,
        loc_b: Optional[Location],
    ) -> bool:
        self.calls += 1
        A, B = content_tokens(text_a), content_tokens(text_b)
        if not A or not B:
            return False
        return len(A & B) / len(A | B) >= self.threshold


def build_client(spec: str, max_tokens: int = 64) -> ModelClient:
    """Construct a client from a ``provider`` or ``provider:model`` spec."""
    provider, _, model = spec.partition(":")
    provider = provider.lower()
    if provider == "anthropic":
        return AnthropicClient(model or "claude-opus-4-8", max_tokens)
    if provider == "openai":
        return OpenAIClient(model or "gpt-5.5", max_tokens)
    if provider == "deepseek":
        return DeepSeekClient(model or "deepseek-v4-pro", max_tokens)
    if provider in ("gemini", "google"):
        return GeminiClient(model or "gemini-3.1-pro-preview", max_tokens)
    raise ValueError(f"unknown judge provider {provider!r} "
                     f"(want anthropic|openai|deepseek|gemini)")
