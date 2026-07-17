# Matcher validation runs — frozen judge caches + reports

Reproducible artifacts behind the M1b matcher-validation numbers. Each
`cache_<judge>.json` is that judge's frozen `(finding_a, finding_b) -> verdict`
decision cache over the ambiguous band; the P/R in each `AGREEMENT_<judge>.md`
regenerates from its cache with **zero new API calls**:

```
python scripts/validate_matcher.py --judge <provider>:<model> \
    --flip-sample 0 --cache runs/matcher/cache_<judge>.json
python scripts/matcher_cross_judge.py \
    deepseek-v4-pro=runs/matcher/cache_deepseek-v4-pro.json \
    opus-4.8=runs/matcher/cache_opus-4.8.json \
    gpt-5.5=runs/matcher/cache_gpt-5.5.json
```

## Results (full 2,220-pair oracle-derived gold set, 1,031-pair judge band)

Hybrid matcher = deterministic location+lexical first pass → LLM judge on the band.

| Judge (family) | band coverage | precision | recall | F1 | raw flip-rate |
|---|---|---|---|---|---|
| DeepSeek V4-Pro | 1031/1031 | 0.9991 | 0.9964 | **0.9977** | 0.0 |
| Opus 4.8 | 1031/1031 | 0.9991 | 0.9982 | **0.9986** | 0.0 |
| GPT-5.5 | 1031/1031 | 0.9973 | 1.0 | **0.9987** | ~0 |

**Cross-judge (all 1031 band pairs decided by all three families):**

- κ vs gold: DeepSeek 0.9767 · Opus 0.9859 · GPT-5.5 0.9857
- pairwise inter-judge κ: DeepSeek↔Opus **0.9814** · DeepSeek↔GPT-5.5 0.9717 · Opus↔GPT-5.5 0.9810
- **majority-vote matcher: P 0.9989 / R 0.9989 / F1 0.9989**

(These are computed over the *full* band — including the hardest ambiguous pairs
the frontier judges most often disagree on — so the κ is a touch lower than an
easy-subset would show, and more honest for it.)

## Notes

- **Three full-coverage frontier judges**, each F1 ≈ 0.998 with a ~0 raw flip-rate.
  The near-identical results across three *different families* (inter-judge κ ≥
  0.972) are the anti-self-preference-bias evidence: the matcher does not depend on
  judge family.
- **GPT-5.5 request-pattern gotcha (diagnosed + fixed):** the GPT-5.5 endpoint
  returns empty 200 responses when requests are fired *truly back-to-back* by a
  thread pool's `map` — which manifested as up to ~95% "parse failures" during
  concurrent/rapid runs. It is **not** truncation (probed pairs reason only ~50–90
  tokens at `reasoning_effort=low`; a 65k cap made no difference), TPM (quota
  barely dented), endpoint health (a 60-call raw burst hit 60/60 in the same
  window a failing run did), or thread-safety (main- and worker-thread calls both
  succeeded 8/8 in isolation). A **sequential main-thread loop with the natural
  per-call gap** decides these same pairs 60/60 with zero errors. Fix: `prejudge`
  runs sequentially when `concurrency <= 1` (see `reviewconverge/matcher/
  validation.py`); GPT-5.5's full-coverage cache was filled that way. DeepSeek and
  Opus are unaffected (full coverage at concurrency 8).
- **Honesty caveat**: gold labels are oracle-derived (paraphrases of one seeded
  defect = same; distinct seeded defects = different), which are cleaner than
  field findings. Independent human second-opinion labels (κ vs a non-oracle
  source) remain the next validation step.
