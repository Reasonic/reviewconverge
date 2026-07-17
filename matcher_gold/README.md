# Matcher gold set — labeled finding pairs

Because every metric rests on the finding-equivalence matcher, the matcher must be
validated, not assumed. This directory holds the labeled finding pairs (same issue
/ different issue) used to measure matcher precision/recall and agreement.

Contents:
- `pairs.jsonl`      — labeled finding pairs. The current set is **oracle-derived**
  (positives = paraphrases of one seeded defect; negatives = distinct defects,
  same-artifact pairs as hard negatives). Regenerate with
  `python scripts/build_matcher_gold.py` (optionally `--sample N` for a balanced
  human-labeling queue).
- `second_opinion.jsonl` — independent human + frontier-model labels over the same
  `pair_id`s, for inter-rater agreement (κ). **Human-labeling task is set up:**
  `python scripts/build_kappa_sample.py` writes a blinded `kappa_worksheet.csv`
  (250 balanced pairs, oracle answer withheld); a human fills the `label` column
  (`same`/`different`); `python scripts/compute_kappa.py` scores Cohen's κ
  human-vs-oracle (and human-vs-matcher with `--cache`). See `KAPPA_INSTRUCTIONS.md`.
  ⏳ *awaiting human labels* — the journal-grade validation gate.
- `AGREEMENT.md`     — matcher precision/recall + self-agreement/flip-rate.
  Regenerate with `python scripts/validate_matcher.py`.
- `SENSITIVITY.md`   — headline P/R recomputed under threshold perturbation.

## Status

✅ **M1b v0 landed (2026-07-05).** Matcher (`reviewconverge/matcher/`) = location +
lexical deterministic first pass → LLM judge on the ambiguous band → content-keyed
decision cache (determinism-by-construction). Validated against a 2,220-pair
oracle-derived gold set:

- **precision 0.928, recall 0.451, F1 0.606** (deterministic lexical pass only)
- **self-agreement 1.0 / flip-rate 0.0** — the determinism claim, demonstrated
- **precision stable 0.89–0.93** across the whole `tau_mid` sweep; recall is the
  knob-sensitive axis (0.22–0.60)

Reading: the first pass is high-precision and precision-stable, so it rarely
*merges distinct issues*; the recall gap is low-overlap semantic paraphrases, which
is exactly what the LLM judge on the ambiguous band is for.

**LLM judge wired (2026-07-05, `reviewconverge/matcher/judges.py`):** frozen +
versioned prompt (`JUDGE_PROMPT_VERSION`), stdlib-`urllib` clients for Anthropic /
OpenAI / DeepSeek (no SDK dep; keys from env), `LLMJudge` (conservative on parse
error; **aborts loudly on a missing key** rather than degrading to DIFFERENT),
family-rotation rule (judge family ≠ loop family), and an offline `RuleJudge` so the
band path runs in CI. Run it with:

```
python scripts/validate_matcher.py --judge deepseek:deepseek-v4-pro \
    --limit 400 --cache runs/matcher_cache.json     # needs DEEPSEEK_API_KEY
python scripts/validate_matcher.py --rule-judge      # offline, no key
```

Judged-run outputs land in `runs/_scratch/matcher/` (git-ignored) until a real run
is promoted.

**Live judge validation done (2026-07-05).** Three frontier families judged the
full band; the hybrid matcher lifts recall from the deterministic 0.451 to ~0.998
while holding precision. Frozen caches + reports in `../runs/matcher/`:

| Judge | coverage | P | R | F1 | flip |
|---|---|---|---|---|---|
| DeepSeek V4-Pro | full | 0.9991 | 0.9964 | **0.9977** | 0.0 |
| Opus 4.8 | full | 0.9991 | 0.9982 | **0.9986** | 0.0 |
| GPT-5.5 | full | 0.9973 | 1.0 | **0.9987** | ~0 |

Cross-judge (all 1031 pairs decided by all three): pairwise inter-judge **κ 0.972–0.981**,
**majority-vote matcher F1 0.9989**. Three different-family judges near-identical on
the full band = the answer to the self-preference-bias critique. (GPT-5.5 reached
full coverage after fixing a back-to-back-request gotcha on its endpoint; see
`../runs/matcher/README.md`.)

**Next (M1b):** collect independent human/frontier second-opinion labels →
`second_opinion.jsonl` and report κ against a *non-oracle* source (the oracle-derived
labels here are cleaner than field findings). This validation is part of the
*minimum preprintable unit* — reviewers attack the matcher first.
