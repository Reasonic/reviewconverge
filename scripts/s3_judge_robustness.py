#!/usr/bin/env python3
"""S3 (round-2 SHOULD-FIX): LLM-judge self-consistency + pair-order sensitivity.

Reviewer (R2): the paper varies the judge *family* thoroughly but never reports same-judge
self-consistency (resample the same pair) or order sensitivity (is (a,b) judged the same as
(b,a)?). Both are well-documented LLM-judge failure modes. This samples real ambiguous-band
pairs and, with the PRIMARY judge (V4-Pro), judges each three ways WITHOUT caching:
  v1 = decide(a,b) ; v2 = decide(a,b) [self-consistency] ; v3 = decide(b,a) [order swap].
Reports the agreement rates over decided pairs.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reviewconverge.config import load_dotenv  # noqa: E402
from reviewconverge.matcher.judges import LLMJudge, build_client  # noqa: E402
from reviewconverge.schema import Location  # noqa: E402

PAIRS = ROOT / "runs" / "_scratch" / "B" / "collected_pairs.jsonl"
OUT = ROOT / "crossfamily_results" / "s3_judge_robustness.json"
N = 150


def loc(d):
    return None if d is None else Location(**d)


def main():
    load_dotenv()
    all_pairs = [json.loads(l) for l in open(PAIRS, encoding="utf-8")]
    # evenly spaced sample of N (deterministic, no RNG)
    step = max(1, len(all_pairs) // N)
    sample = all_pairs[::step][:N]
    judge = LLMJudge(build_client("deepseek:deepseek-v4-pro"), parse_retries=2)  # V4-Pro: non-reasoning, 64 tok OK

    def three_way(p):
        a, la, b, lb = p["text_a"], loc(p["loc_a"]), p["text_b"], loc(p["loc_b"])
        v1, d1 = judge.decide(a, la, b, lb)
        v2, d2 = judge.decide(a, la, b, lb)     # self-consistency
        v3, d3 = judge.decide(b, lb, a, la)     # order swap
        return (v1, d1, v2, d2, v3, d3)

    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(three_way, sample))

    self_ok = self_tot = swap_ok = swap_tot = 0
    for v1, d1, v2, d2, v3, d3 in res:
        if d1 and d2:
            self_tot += 1; self_ok += (v1 == v2)
        if d1 and d3:
            swap_tot += 1; swap_ok += (v1 == v3)
    out = {
        "n_sampled": len(sample), "judge": "deepseek:deepseek-v4-pro",
        "self_consistency": {"agree": self_ok, "of": self_tot,
                             "rate": round(self_ok / self_tot, 4) if self_tot else None},
        "order_swap": {"agree": swap_ok, "of": swap_tot,
                       "rate": round(swap_ok / swap_tot, 4) if swap_tot else None},
        "judge_calls": judge.calls, "undecided": judge.undecided, "parse_err": judge.parse_errors,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
