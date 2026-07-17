# Matcher validation — precision/recall + self-agreement

Deterministic (no-LLM) matcher over the oracle-derived gold set (`pairs.jsonl`). Regenerate with `python scripts/validate_matcher.py`.

## Precision / recall vs gold labels

| n | TP | FP | FN | TN | precision | recall | F1 | accuracy |
|---|---|---|---|---|---|---|---|---|
| 2220 | 500 | 39 | 610 | 1071 | 0.9276 | 0.4505 | 0.6064 | 0.7077 |

> The lexical first pass is precision-leaning by design: dissimilar wording of the *same* issue (semantic paraphrases) is the recall gap the LLM judge closes on the ambiguous band. FP here are hard negatives (distinct defects sharing an artifact) the lexical score conflates.

## Decision method mix

| method | pairs |
|---|---|
| anchor-disjoint | 990 |
| lexical-fallback | 1031 |
| lexical-high | 199 |

## Self-agreement / flip rate (determinism check)

- runs: 2
- pairs: 2220
- flipped verdicts: 0
- **flip rate: 0.0**
- **self-agreement: 1.0**

> A deterministic first pass / cached verdict flips 0% by construction (PLANS §4.3a.4). This column becomes load-bearing once the stochastic LLM judge is wired in: it reports the judge's raw flip rate before the decision cache pins each verdict.

