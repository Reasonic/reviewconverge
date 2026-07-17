#!/usr/bin/env python3
"""Standalone judger: judge the collected uncached pairs with CONTINUOUS fresh GPT-5.5
calls and write verdicts to the shared cache.

Continuous calls (no cache-hit re-stream idle in between) are the exact pattern that
succeeded 34/34 in probing, so they sidestep the sustained-batch socket wedge that stalls
the in-process judge. Restartable: pairs already in the cache are skipped (decide_pair
returns method="cache"), so a re-run resumes and re-attempts only the still-undecided ones.
After this, `compute_metrics ... --judge openai:gpt-5.5` finds everything cached and writes
the full n=360 output with no further API calls.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reviewconverge.config import load_dotenv  # noqa: E402
from reviewconverge.matcher.cache import DecisionCache  # noqa: E402
from reviewconverge.matcher.core import Matcher  # noqa: E402
from reviewconverge.matcher.judges import LLMJudge, build_client  # noqa: E402
from reviewconverge.schema import Location  # noqa: E402

B = ROOT / "runs" / "_scratch" / "B"
CACHE = B / "gpt_primary_cache.json"
PAIRS = B / "collected_pairs.jsonl"
SAVE_EVERY = 15  # save often so the driver's cache-file poll reliably sees progress
                 # (a slow save cadence can otherwise look like a wedge and trip a restart)


def loc_of(d):
    return None if d is None else Location(**d)


def main():
    load_dotenv()
    cache = DecisionCache.load(CACHE) if CACHE.exists() else DecisionCache()
    judge = LLMJudge(build_client("openai:gpt-5.5"), parse_retries=3)
    matcher = Matcher(judge=judge, cache=cache)
    pairs = [json.loads(l) for l in open(PAIRS, encoding="utf-8")]
    n = len(pairs)
    print(f"loaded {n} collected pairs; cache starts at {len(cache)} verdicts", flush=True)
    skipped = 0
    t0 = time.time()
    try:
        for i, p in enumerate(pairs, 1):
            dec = matcher.decide_pair(p["text_a"], loc_of(p["loc_a"]),
                                      p["text_b"], loc_of(p["loc_b"]))
            if dec.method == "cache":
                skipped += 1
            if i % SAVE_EVERY == 0:
                cache.save(CACHE)
                el = time.time() - t0
                rate = judge.calls / el if el else 0
                print(f"  {i}/{n} | cache {len(cache)} | judged {judge.calls} "
                      f"undecided {judge.undecided} parse_err {judge.parse_errors} "
                      f"transport_err {judge.transport_errors} | skip {skipped} | {rate:.2f} calls/s",
                      flush=True)
    finally:
        cache.save(CACHE)
    print(f"DONE: {n} pairs | judge calls {judge.calls} | undecided {judge.undecided} | "
          f"parse_err {judge.parse_errors} | final cache {len(cache)} verdicts", flush=True)


if __name__ == "__main__":
    main()
