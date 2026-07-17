#!/usr/bin/env python3
"""Validate the finding-equivalence matcher against the gold set.

Runs the deterministic (no-LLM) matcher over ``matcher_gold/pairs.jsonl`` and
reports the sub-study numbers from PLANS §4.2:

- precision / recall / F1 / accuracy vs the oracle-derived labels,
- self-agreement / flip rate (the determinism check), and
- a threshold-sensitivity sweep.

Default (no judge) writes ``matcher_gold/AGREEMENT.md`` + ``SENSITIVITY.md`` — the
canonical committed $0 read. With a judge attached, the LLM (or offline rule)
judge decides the ambiguous band; results go to a judge-specific file and the
judge's *raw* flip rate (cache off) is reported before the decision cache pins it.

Usage::

    python scripts/validate_matcher.py [GOLD_JSONL]           # deterministic
    python scripts/validate_matcher.py --rule-judge           # offline band judge
    python scripts/validate_matcher.py --judge deepseek:deepseek-v4-pro \\
        --limit 400 --cache runs/matcher_cache.json           # live judge (needs key)
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.config import key_status, load_dotenv  # noqa: E402
from reviewconverge.matcher.core import Matcher  # noqa: E402
from reviewconverge.matcher.cache import DecisionCache  # noqa: E402
from reviewconverge.matcher.judges import (  # noqa: E402
    JudgeConfigError,
    LLMJudge,
    RuleJudge,
    build_client,
)
from reviewconverge.matcher.validation import (  # noqa: E402
    band_pairs,
    evaluate,
    load_gold_jsonl,
    prejudge,
    self_agreement,
    threshold_sensitivity,
)

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "matcher_gold"
# Exploratory judged runs are scratch (git-ignored) until a real run is promoted.
JUDGE_OUT = ROOT / "runs" / "_scratch" / "matcher"


def _agreement_md(report, methods, agree) -> str:
    d = report.to_dict()
    lines = [
        "# Matcher validation — precision/recall + self-agreement",
        "",
        "Deterministic (no-LLM) matcher over the oracle-derived gold set "
        "(`pairs.jsonl`). Regenerate with `python scripts/validate_matcher.py`.",
        "",
        "## Precision / recall vs gold labels",
        "",
        "| n | TP | FP | FN | TN | precision | recall | F1 | accuracy |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| {d['n']} | {d['tp']} | {d['fp']} | {d['fn']} | {d['tn']} | "
        f"{d['precision']} | {d['recall']} | {d['f1']} | {d['accuracy']} |",
        "",
        "> The lexical first pass is precision-leaning by design: dissimilar "
        "wording of the *same* issue (semantic paraphrases) is the recall gap the "
        "LLM judge closes on the ambiguous band. FP here are hard negatives "
        "(distinct defects sharing an artifact) the lexical score conflates.",
        "",
        "## Decision method mix",
        "",
        "| method | pairs |",
        "|---|---|",
    ]
    for m in sorted(methods):
        lines.append(f"| {m} | {methods[m]} |")
    lines += [
        "",
        "## Self-agreement / flip rate (determinism check)",
        "",
        f"- runs: {agree['runs']}",
        f"- pairs: {agree['n']}",
        f"- flipped verdicts: {agree['flipped']}",
        f"- **flip rate: {agree['flip_rate']}**",
        f"- **self-agreement: {agree['self_agreement']}**",
        "",
        "> A deterministic first pass / cached verdict flips 0% by construction "
        "(PLANS §4.3a.4). This column becomes load-bearing once the stochastic LLM "
        "judge is wired in: it reports the judge's raw flip rate before the "
        "decision cache pins each verdict.",
        "",
    ]
    return "\n".join(lines)


def _sensitivity_md(rows) -> str:
    lines = [
        "# Matcher threshold sensitivity",
        "",
        "Headline P/R recomputed across a grid of the deterministic matcher's "
        "decision boundary (`tau_mid`, the lexical-fallback threshold that decides "
        "every pair not resolved by the auto-same/auto-different shortcuts). The "
        "curve is the precision/recall trade-off; a broad F1 plateau is the "
        "evidence that conclusions do not hinge on a knob choice.",
        "",
        "| tau_mid | precision | recall | F1 | accuracy |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['tau_mid']} | {r['precision']} | "
            f"{r['recall']} | {r['f1']} | {r['accuracy']} |"
        )
    if rows:
        f1s = [r["f1"] for r in rows]
        precs = [r["precision"] for r in rows]
        recs = [r["recall"] for r in rows]
        lines += [
            "",
            f"- F1 range: {min(f1s)} – {max(f1s)} (spread {round(max(f1s) - min(f1s), 4)})",
            f"- precision range: {min(precs)} – {max(precs)}",
            f"- recall range: {min(recs)} – {max(recs)}",
            "",
        ]
    return "\n".join(lines)


def _run_deterministic(pairs) -> int:
    matcher = Matcher(judge=None)  # deterministic lexical matcher
    report, methods = evaluate(matcher, pairs, use_cache=False)
    agree = self_agreement(matcher, pairs, runs=2, use_cache=False)
    rows = threshold_sensitivity(pairs)

    (GOLD / "AGREEMENT.md").write_text(_agreement_md(report, methods, agree) + "\n", encoding="utf-8")
    (GOLD / "SENSITIVITY.md").write_text(_sensitivity_md(rows) + "\n", encoding="utf-8")

    d = report.to_dict()
    print("-" * 60)
    print(f"gold pairs: {d['n']}  (same={d['tp'] + d['fn']}  different={d['fp'] + d['tn']})")
    print(f"precision: {d['precision']}   recall: {d['recall']}   "
          f"F1: {d['f1']}   accuracy: {d['accuracy']}")
    print(f"self-agreement: {agree['self_agreement']}   flip-rate: {agree['flip_rate']}")
    if rows:
        f1s = [r["f1"] for r in rows]
        print(f"threshold sensitivity: F1 in [{min(f1s)}, {max(f1s)}] over {len(rows)} grid points")
    print(f"wrote: {GOLD / 'AGREEMENT.md'}, {GOLD / 'SENSITIVITY.md'}")
    return 0


def _run_with_judge(pairs, judge, label: str, cache_path, flip_sample: int,
                    concurrency: int, max_new=None) -> int:
    """Evaluate with a judge on the ambiguous band; report judged P/R + raw flip rate."""
    cache = DecisionCache.load(cache_path) if (cache_path and cache_path.exists()) else DecisionCache()

    # Judge the band concurrently into the cache (resumable via cache_path), then
    # score cache-driven so the judge is called once per unique band pair.
    band = band_pairs(pairs)
    made, undecided = prejudge(band, judge, cache, concurrency=concurrency,
                               save_path=cache_path, max_new=max_new)
    if undecided:
        print(f"WARNING: {undecided} band pair(s) undecided (errored/unparseable) and left "
              f"uncached. Re-run the same command to retry only those.")
    # Score with a JUDGE-LESS matcher over a cache *copy*: decided band pairs
    # replay their cached verdict; any still-undecided band pair falls to the
    # deterministic pass. Never re-judges and never writes to the real cache, so
    # the flow can't poison it (an undecided pair stays uncached for the retry).
    matcher = Matcher(judge=None, cache=cache.copy())
    report, methods = evaluate(matcher, pairs, use_cache=True)

    # Raw judge flip rate: re-judge a bounded band sample with the cache OFF (two
    # concurrent passes). Skipped when --flip-sample 0 (avoids extra spend on
    # expensive providers). These re-judgments are deliberately NOT cached.
    flip_band = band[:flip_sample] if flip_sample > 0 else []

    def verdicts():
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
            return list(ex.map(
                lambda p: bool(judge(p.a_text, p.a_location(), p.b_text, p.b_location())),
                flip_band,
            ))

    n_flip = len(flip_band)
    if n_flip:
        run1, run2 = verdicts(), verdicts()
        flips = sum(1 for a, b in zip(run1, run2) if a != b)
        agree = {"n": n_flip, "runs": 2, "flip_rate": round(flips / n_flip, 4),
                 "self_agreement": round(1 - flips / n_flip, 4)}
    else:
        agree = {"n": 0, "runs": 0, "flip_rate": None, "self_agreement": None}

    if cache_path:
        cache.save(cache_path)  # the real cache (decided judge verdicts only)

    print(f"(band judged: {len(band)} pairs, {made} new judgments, {undecided} undecided)")
    flip_txt = "skipped" if agree["flip_rate"] is None else str(agree["flip_rate"])
    d = report.to_dict()
    JUDGE_OUT.mkdir(parents=True, exist_ok=True)
    out = JUDGE_OUT / f"AGREEMENT_{label}.md"
    lines = [
        f"# Matcher validation — judged band ({label})",
        "",
        f"Judge decides the ambiguous band (deterministic first pass unchanged). "
        f"Pairs evaluated: {d['n']}. Band pairs judged: {len(band)} "
        f"({undecided} undecided/uncached).",
        "",
        "| precision | recall | F1 | accuracy |",
        "|---|---|---|---|",
        f"| {d['precision']} | {d['recall']} | {d['f1']} | {d['accuracy']} |",
        "",
        f"- raw judge flip-rate (cache off, {agree['n']} band pairs, {agree['runs']} runs): "
        f"**{flip_txt}**"
        + (f" (self-agreement {agree['self_agreement']})" if agree['flip_rate'] is not None else ""),
    ]
    if isinstance(judge, LLMJudge):
        lines.append(
            f"- judge calls: {judge.calls}  parse-errors: {judge.parse_errors}  "
            f"transport-errors: {judge.transport_errors}  family: {judge.family}"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("-" * 60)
    print(f"[judge={label}] pairs: {d['n']}  precision: {d['precision']}  "
          f"recall: {d['recall']}  F1: {d['f1']}")
    print(f"raw judge flip-rate: {flip_txt}")
    if isinstance(judge, LLMJudge):
        print(f"judge calls: {judge.calls}  parse-errors: {judge.parse_errors}  "
              f"transport-errors: {judge.transport_errors}")
    print(f"wrote: {out}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate the finding-equivalence matcher.")
    ap.add_argument("gold", nargs="?", default=str(GOLD / "pairs.jsonl"))
    ap.add_argument("--judge", metavar="PROVIDER[:MODEL]",
                    help="live LLM judge on the band (anthropic|openai|deepseek); needs API key")
    ap.add_argument("--rule-judge", action="store_true",
                    help="offline deterministic band judge (no network/spend)")
    ap.add_argument("--limit", type=int, default=None, help="evaluate only the first N pairs")
    ap.add_argument("--cache", default=None, help="decision-cache JSON to load/save")
    ap.add_argument("--flip-sample", type=int, default=50,
                    help="band pairs used for the raw flip-rate measurement")
    ap.add_argument("--concurrency", type=int, default=8,
                    help="parallel judge calls (I/O-bound; default 8)")
    ap.add_argument("--parse-retries", type=int, default=3,
                    help="re-attempts on an empty/unparseable/transient judge reply (default 3)")
    ap.add_argument("--call-delay", type=float, default=0.0,
                    help="seconds to pause before each judge API call (paces a flaky endpoint)")
    ap.add_argument("--max-new", type=int, default=None,
                    help="cap how many still-uncached band pairs to judge this run")
    ap.add_argument("--keys", action="store_true",
                    help="print which provider keys are visible (existence only) and exit")
    args = ap.parse_args(argv[1:])

    # Load a git-ignored .env at repo root (real env vars take precedence).
    load_dotenv()
    if args.keys:
        for name, present in key_status().items():
            print(f"{name}: {'set' if present else 'unset'}")
        return 0

    gold_path = Path(args.gold)
    if not gold_path.exists():
        print(f"error: gold set not found: {gold_path}\n"
              f"run: python scripts/build_matcher_gold.py", file=sys.stderr)
        return 2

    pairs = load_gold_jsonl(gold_path)
    if args.limit:
        pairs = pairs[: args.limit]

    if args.judge:
        judge = LLMJudge(build_client(args.judge), parse_retries=args.parse_retries,
                         call_delay=args.call_delay)
        try:
            return _run_with_judge(pairs, judge, args.judge.replace(":", "_"),
                                   Path(args.cache) if args.cache else None,
                                   args.flip_sample, args.concurrency, args.max_new)
        except JudgeConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if args.rule_judge:
        return _run_with_judge(pairs, RuleJudge(), "rule",
                               Path(args.cache) if args.cache else None,
                               args.flip_sample, args.concurrency, args.max_new)
    return _run_deterministic(pairs)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
