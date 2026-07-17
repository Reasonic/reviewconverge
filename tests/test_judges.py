"""Tests for the LLM-judge wiring (M1b). All offline — no network, no keys."""

from __future__ import annotations

import pytest

from reviewconverge.schema import Location
from reviewconverge.matcher import Matcher
from reviewconverge.matcher.judges import (
    JudgeConfigError,
    JudgeParseError,
    LLMJudge,
    RuleJudge,
    build_client,
    build_user_prompt,
    model_family,
    parse_verdict,
    rotate_judge_family,
    same_family_clash,
    spec_family,
)
from reviewconverge.matcher.validation import GoldPair, band_pairs, prejudge, self_agreement
from reviewconverge.matcher.cache import DecisionCache
from reviewconverge.matcher.judges import (
    AnthropicClient,
    DeepSeekClient,
    GeminiClient,
    OpenAIClient,
    _suggested_delay,
)


# -- prompt + parsing -----------------------------------------------------
def test_parse_verdict_variants():
    assert parse_verdict("SAME") is True
    assert parse_verdict("DIFFERENT") is False
    assert parse_verdict("DIFFERENT\nthey assert different problems") is False
    assert parse_verdict("same — both are the divide-by-zero issue") is True
    assert parse_verdict("- **DIFFERENT**") is False
    assert parse_verdict("The answer is SAME.") is True  # single unambiguous mention


def test_parse_verdict_ambiguous_raises():
    with pytest.raises(JudgeParseError):
        parse_verdict("maybe, could be same or different")
    with pytest.raises(JudgeParseError):
        parse_verdict("")


def test_build_user_prompt_contains_both_and_locations():
    p = build_user_prompt("claim one", Location("f.py", 4, 5), "claim two", None)
    assert "claim one" in p and "claim two" in p
    assert "f.py lines 4-5" in p
    assert "(unlocalized)" in p


# -- LLMJudge over a fake client -----------------------------------------
class _FakeClient:
    family = "fake"
    model = "fake-1"

    def __init__(self, reply=None, raise_exc=None):
        self.reply = reply
        self.raise_exc = raise_exc
        self.seen = []

    def complete(self, system, user):
        self.seen.append((system, user))
        if self.raise_exc:
            raise self.raise_exc
        return self.reply


def test_llm_judge_parses_client_reply():
    j = LLMJudge(_FakeClient(reply="SAME\nboth describe the off-by-one"))
    assert j("a", None, "b", None) is True
    assert j.calls == 1 and j.parse_errors == 0

    j2 = LLMJudge(_FakeClient(reply="DIFFERENT"))
    assert j2("a", None, "b", None) is False


def test_llm_judge_parse_error_defaults_conservative():
    j = LLMJudge(_FakeClient(reply="I am not sure, same or different"))
    assert j("a", None, "b", None) is False  # conservative default
    assert j.parse_errors == 1


def test_llm_judge_parse_retries_then_succeeds():
    # Two unparseable replies (empty / no verdict), then a clean one: a fresh call
    # resolves it, so the pair is decided rather than lost.
    replies = iter(["", "hmm not sure", "SAME"])

    class _Seq:
        family = "seq"
        model = "s"

        def complete(self, system, user):
            return next(replies)

    j = LLMJudge(_Seq(), parse_retries=2)
    v, decided = j.decide("a", None, "b", None)
    assert decided and v is True
    assert j.calls == 3 and j.parse_errors == 2


def test_llm_judge_transport_error_counted():
    j = LLMJudge(_FakeClient(raise_exc=RuntimeError("HTTP 500")))
    assert j("a", None, "b", None) is False
    assert j.transport_errors == 1 and j.calls == 1


def test_llm_judge_undecided_counter_on_exhausted_retries():
    # A persistent transport failure (e.g. the account ran out of credit) exhausts the
    # retries -> decide() reports decided=False and the `undecided` counter increments.
    # compute_metrics reads this counter to refuse writing a credit-interrupted result.
    j = LLMJudge(_FakeClient(raise_exc=RuntimeError("HTTP 429 insufficient_quota")),
                 parse_retries=2)
    verdict, decided = j.decide("a", None, "b", None)
    assert verdict is False and decided is False
    assert j.undecided == 1
    assert j.transport_errors == 3  # (parse_retries + 1) attempts, all failed


def test_llm_judge_config_error_propagates_not_swallowed():
    # A missing key / misconfiguration must abort the run, not degrade to DIFFERENT.
    j = LLMJudge(_FakeClient(raise_exc=JudgeConfigError("ANTHROPIC_API_KEY is not set")))
    with pytest.raises(JudgeConfigError):
        j("a", None, "b", None)
    assert j.transport_errors == 0


# -- family rotation ------------------------------------------------------
def test_model_family():
    assert model_family("claude-opus-4-8") == "anthropic"
    assert model_family("gpt-5.5") == "openai"
    assert model_family("deepseek-v4-flash") == "deepseek"
    assert model_family("mystery-model") == "unknown"


def test_rotate_judge_family_differs_from_loop():
    # loop is DeepSeek -> judge must not be DeepSeek
    assert rotate_judge_family("deepseek-v4-flash") != "deepseek"
    # loop is Claude -> judge must not be Anthropic
    assert rotate_judge_family("claude-haiku-4-5") != "anthropic"
    # explicit pool
    fam = rotate_judge_family("gpt-5.4-mini", available=("openai", "anthropic"))
    assert fam == "anthropic"


def test_spec_family_from_model_and_provider():
    assert spec_family("deepseek:deepseek-v4-pro") == "deepseek"
    assert spec_family("openai:gpt-5.5") == "openai"
    assert spec_family("anthropic:claude-opus-4-8") == "anthropic"
    assert spec_family("google:gemini-3.1-pro-preview") == "google"
    assert spec_family("anthropic") == "anthropic"   # provider-only spec still resolves
    assert spec_family("mystery") == "unknown"


def test_same_family_clash_guard():
    # audit #7: the campaign judged a V4-Flash loop with a V4-Pro judge (both DeepSeek).
    assert same_family_clash("deepseek:deepseek-v4-pro", ["deepseek-v4-flash"]) == "deepseek"
    # a cross-family judge clears the guard
    assert same_family_clash("openai:gpt-5.5", ["deepseek-v4-flash"]) is None
    assert same_family_clash("anthropic:claude-opus-4-8", ["deepseek-v4-flash"]) is None
    # clashes if ANY loop model shares the family (mixed campaign)
    assert same_family_clash("openai:gpt-5.5", ["deepseek-v4-flash", "gpt-5.5"]) == "openai"
    # an unknown judge family never clashes (we don't guess)
    assert same_family_clash("mystery:xyz-1", ["deepseek-v4-flash"]) is None
    # empty loop set -> no clash
    assert same_family_clash("deepseek:deepseek-v4-pro", []) is None


def test_openai_reasoning_effort_detection():
    assert OpenAIClient("gpt-5.5").reasoning_effort == "low"    # reasoning model
    assert OpenAIClient("o3").reasoning_effort == "low"
    assert OpenAIClient("gpt-4o").reasoning_effort is None       # non-reasoning
    assert OpenAIClient("gpt-5.5", reasoning_effort="high").reasoning_effort == "high"
    assert DeepSeekClient().reasoning_effort is None             # not sent for DeepSeek


def test_build_client_types_and_unknown():
    assert isinstance(build_client("anthropic"), AnthropicClient)
    assert isinstance(build_client("openai:gpt-5.5"), OpenAIClient)
    assert isinstance(build_client("deepseek"), DeepSeekClient)
    assert isinstance(build_client("gemini"), GeminiClient)
    assert isinstance(build_client("google:gemini-3.1-pro-preview"), GeminiClient)
    assert build_client("openai:gpt-5.5").model == "gpt-5.5"
    with pytest.raises(ValueError):
        build_client("mistral")


def test_gemini_client_floors_tokens_and_defaults():
    # build_client passes its default max_tokens=64, which would truncate a thinking
    # model's verdict to empty; GeminiClient floors it. Model string + retries pinned.
    c = build_client("gemini")
    assert c.model == "gemini-3.1-pro-preview" and c.family == "google"
    assert c.max_tokens == GeminiClient._MIN_TOKENS   # 64 floored up
    assert c.retries >= 6 and c.backoff >= 2.0        # outlast a per-minute quota
    # An explicit larger cap is respected, not clamped down.
    assert GeminiClient(max_tokens=32768).max_tokens == 32768


def test_openai_reasoning_client_floors_tokens():
    # Regression: build_client passes its default max_tokens=64 (sized for non-reasoning
    # judges). A GPT-5.x / o-series reasoning model spends that budget on hidden reasoning
    # tokens and truncates the verdict to empty content -> undecided. The client must floor
    # the cap for reasoning models (like GeminiClient), but leave non-reasoning ones alone.
    for spec in ("openai:gpt-5.5", "openai:o3"):
        c = build_client(spec)  # default max_tokens=64
        assert c.reasoning_effort == "low"
        assert c.max_tokens >= OpenAIClient._MIN_REASONING_TOKENS, f"{spec} not floored"
    # Non-reasoning OpenAI model keeps the caller's small cap (no reasoning to truncate it).
    assert build_client("openai:gpt-4o").max_tokens == 64
    assert OpenAIClient("gpt-4o").reasoning_effort is None
    # An explicit larger cap is respected, never clamped down.
    assert OpenAIClient("gpt-5.5", max_tokens=32768).max_tokens == 32768
    # Read timeout + retries are bounded so a wedged socket aborts fast (~90s over the
    # nested attempts) -> undecided -> the run continues, instead of stalling tens of
    # minutes on a hung read that a fresh process would clear.
    assert OpenAIClient("gpt-5.5").timeout == 45.0
    assert OpenAIClient("gpt-5.5").retries == 1


def test_suggested_delay_prefers_header_then_google_body():
    # OpenAI/Anthropic style: numeric Retry-After header wins.
    assert _suggested_delay({"Retry-After": "12"}, "") == pytest.approx(12.0)
    # Google OpenAI-compat 429: no header, delay is in the body's RetryInfo.
    body = ('[{"error":{"code":429,"status":"RESOURCE_EXHAUSTED","details":'
            '[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"38s"}]}}]')
    assert _suggested_delay({}, body) == pytest.approx(38.0)
    # Neither present -> None (caller falls back to exponential backoff).
    assert _suggested_delay({}, '{"error":"nope"}') is None


def test_http_honors_google_retry_delay_and_caps(monkeypatch):
    import io
    import urllib.error
    import reviewconverge.matcher.judges as J

    slept, calls = [], {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            body = (b'[{"error":{"code":429,"details":[{"@type":"google.rpc.RetryInfo",'
                    b'"retryDelay":"900s"}]}}]')  # absurd suggestion -> must be capped
            raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, io.BytesIO(body))

        class _Resp:
            def read(self): return b'{"ok": true}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _Resp()

    monkeypatch.setattr(J.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(J.time, "sleep", lambda s: slept.append(s))
    out = J._http_post_json("https://x", {}, {}, retries=3, backoff=1.0, max_backoff=45.0)
    assert out == {"ok": True} and calls["n"] == 2
    assert slept and slept[0] <= 45.0 and slept[0] >= 38.0  # honored, but capped at max_backoff


# -- RuleJudge + Matcher integration -------------------------------------
def test_rule_judge_deterministic_threshold():
    rj = RuleJudge(threshold=0.5)
    # heavy token overlap -> same
    assert rj("the divisor is never checked", None, "the divisor is not checked", None) is True
    # disjoint content -> different
    assert rj("alpha beta gamma", None, "delta epsilon zeta", None) is False


def test_matcher_uses_judge_on_band():
    # extreme thresholds force everything into the band -> judge decides
    m = Matcher(judge=RuleJudge(threshold=0.0), tau_high=0.999, tau_low=0.0)
    d = m.decide_pair("some claim here", Location("f.py", 1, 1),
                      "another claim there", Location("f.py", 1, 1))
    assert d.method == "llm" and d.same is True  # RuleJudge(0.0) always same on nonempty


# -- flip-rate detection --------------------------------------------------
class _CountingFlipJudge:
    """Alternates verdict by call index; over 2 passes of an odd-length list every
    verdict flips, so self_agreement must report flip_rate 1.0."""

    family = "mock"

    def __init__(self):
        self.n = 0

    def __call__(self, *a):
        v = (self.n % 2 == 0)
        self.n += 1
        return v


def _band_pairs(n):
    # unlocalized, low-overlap texts so the deterministic pass sends them to the judge
    return [GoldPair(pair_id=f"p{i}", a_text=f"alpha word {i}", b_text=f"omega token {i}",
                     label=True, source="test") for i in range(n)]


def test_self_agreement_detects_judge_flips():
    m = Matcher(judge=_CountingFlipJudge(), tau_high=0.999, tau_low=0.0)
    res = self_agreement(m, _band_pairs(3), runs=2, use_cache=False)
    assert res["flip_rate"] == 1.0 and res["self_agreement"] == 0.0


def test_cache_pins_verdict_despite_flaky_judge():
    # With the cache ON, the first verdict is frozen; a flaky judge can't change it.
    m = Matcher(judge=_CountingFlipJudge(), tau_high=0.999, tau_low=0.0)
    pairs = _band_pairs(3)
    res = self_agreement(m, pairs, runs=2, use_cache=True)
    assert res["flip_rate"] == 0.0


# -- concurrent prejudge --------------------------------------------------
def test_prejudge_concurrent_fills_cache_and_resumable(tmp_path):
    band = [
        GoldPair(pair_id=f"p{i}", a_text=f"the divisor is never checked {i}",
                 b_text=f"division by zero is possible {i}", label=True, source="t")
        for i in range(8)
    ]
    cache = DecisionCache()
    made, undecided = prejudge(band, RuleJudge(threshold=0.0), cache, concurrency=4)
    assert made == 8 and undecided == 0 and len(cache) == 8  # every band pair judged once

    # Re-run replays cache -> no new judgments (resumable / idempotent).
    made2, _ = prejudge(band, RuleJudge(threshold=0.0), cache, concurrency=4)
    assert made2 == 0

    # Incremental save is loadable and complete.
    p = tmp_path / "cache.json"
    fresh = DecisionCache()
    prejudge(band, RuleJudge(threshold=0.0), fresh, concurrency=4, save_path=p, save_every=3)
    assert p.exists() and len(DecisionCache.load(p)) == 8


def test_prejudge_does_not_cache_undecided():
    # A judge that errors on every call (undecided) must leave the cache empty so
    # a re-run retries, rather than freezing wrong verdicts into the oracle.
    class _ErroringClient:
        family = "err"
        model = "err-1"

        def complete(self, system, user):
            raise RuntimeError("HTTP 503")

    band = [
        GoldPair(pair_id=f"p{i}", a_text=f"claim alpha {i}", b_text=f"claim beta {i}",
                 label=True, source="t")
        for i in range(5)
    ]
    judge = LLMJudge(_ErroringClient())
    cache = DecisionCache()
    made, undecided = prejudge(band, judge, cache, concurrency=3)
    assert made == 0 and undecided == 5 and len(cache) == 0
    assert judge.transport_errors == 5


def test_scoring_over_cache_copy_never_poisons_real_cache():
    # Regression: scoring must read the cache, never re-judge/write it. An
    # undecided band pair must stay uncached so a re-run retries it.
    from reviewconverge.matcher.core import Matcher
    from reviewconverge.matcher.validation import evaluate

    class _Err:
        family = "err"
        model = "e"

        def complete(self, system, user):
            raise RuntimeError("HTTP 503")

    band = _band_pairs(4)  # unlocalized, low-overlap -> land in the judge band
    judge = LLMJudge(_Err())
    cache = DecisionCache()
    made, undecided = prejudge(band, judge, cache, concurrency=2)
    assert made == 0 and undecided == 4 and len(cache) == 0

    # Score with a judge-less matcher over a COPY: real cache stays empty.
    evaluate(Matcher(judge=None, cache=cache.copy()), band, use_cache=True)
    assert len(cache) == 0  # nothing poisoned -> undecided pairs retried next run


def test_http_retry_on_transient_then_succeeds(monkeypatch):
    import io
    import urllib.error
    import reviewconverge.matcher.judges as J

    calls = {"n": 0}

    class _Resp:
        def __init__(self, body): self._b = body.encode()
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b"busy"))
        return _Resp('{"ok": true}')

    monkeypatch.setattr(J.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(J.time, "sleep", lambda s: None)
    out = J._http_post_json("https://x", {}, {"a": 1}, retries=3, backoff=0.001)
    assert out == {"ok": True} and calls["n"] == 3  # retried twice, then ok


def test_http_no_retry_on_auth_error(monkeypatch):
    import io
    import urllib.error
    import reviewconverge.matcher.judges as J

    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 401, "unauth", {}, io.BytesIO(b"bad key"))

    monkeypatch.setattr(J.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(J.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        J._http_post_json("https://x", {}, {}, retries=3)
    assert calls["n"] == 1  # 401 is permanent -> no retries


def test_prejudge_concurrency_1_uses_sequential_path():
    band = [
        GoldPair(pair_id=f"p{i}", a_text=f"the same claim {i}", b_text=f"the same claim {i}",
                 label=True, source="t")
        for i in range(4)
    ]
    cache = DecisionCache()
    made, undecided = prejudge(band, RuleJudge(threshold=0.0), cache, concurrency=1)
    assert made == 4 and undecided == 0 and len(cache) == 4


def test_prejudge_max_new_caps_attempts():
    band = [
        GoldPair(pair_id=f"p{i}", a_text=f"claim alpha {i}", b_text=f"claim beta {i}",
                 label=True, source="t")
        for i in range(6)
    ]
    cache = DecisionCache()
    made, undecided = prejudge(band, RuleJudge(threshold=0.0), cache, concurrency=2, max_new=3)
    assert made == 3 and len(cache) == 3  # only 3 of 6 uncached pairs attempted


def test_band_pairs_excludes_deterministic():
    pairs = [
        GoldPair("identical", "same exact claim", "same exact claim", True, "t"),   # lexical-high
        GoldPair("disjoint", "alpha beta gamma", "delta epsilon zeta", False, "t",
                 a_unit="a.py", a_start=1, a_end=1, b_unit="b.py", b_start=9, b_end=9),  # anchor-disjoint
    ]
    ids = {p.pair_id for p in band_pairs(pairs)}
    assert "identical" not in ids and "disjoint" not in ids
