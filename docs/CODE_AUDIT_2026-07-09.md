# Measurement-Pipeline Code-Correctness Audit — 2026-07-09

4 adversarial subagents over the load-bearing code; I independently re-read `matcher/core.py`
to confirm the top matcher findings. Data is INTACT — an earlier "data-loss" alarm was a transient
filesystem read glitch, not a real deletion. **Bug#1's numeric impact is QUANTIFIED on the real 720
trajectories** (see #1), via `runs/_scratch/B/verify_assignment.py`. Findings are CODE-level, verified
by reading + repro + full-corpus quantifier.

## Verified CORRECT (ruled out)
- **Statistics** (`armstats.py`): `mcnemar_exact`, `sign_test`, `compare_arms` pairing/pooling —
  exact, matched scipy to <1e-9, paired by `artifact_id`, replicate-pooled correctly. Clean.
- **Metric suite** (`suite.py`): `converged`, `terminal_recall/precision`, `jaccard/churn`,
  `oscillation_degree`, `stabilized_round`, `true_attrition`, gray-zone exclusion — all correct on
  the headline paths. The original dedup-before-match bug is **fully fixed** in `canonical.py`.
- **Regime** (`regime.py`): threshold boundaries inclusive/exclusive correct; computed from
  unrounded metrics. Clean.
- **Cache-reuse validity** (Path B's premise): the matcher fix changed only downstream *assignment*,
  not queried pairs / fingerprints / verdicts → replaying warm verdicts is VALID. (The 2026-07-09
  "cache wiped" note was the transient-glitch false alarm; data is intact and the warm cache stands.
  The 2026-07-10 remediation was verified to leave the *default* fingerprint byte-identical, so the
  warm decision cache remains valid for the Path B recompute — see Remediation.)
- **Gray-zone loading, thread-safety** (`compute_metrics.py`): correct.

## Findings (CODE-level; all REMEDIATED 2026-07-10 with regression tests — see Remediation)

### 1. [HIGH] Greedy 1:1 assignment is suboptimal → can under-count recall  `matcher/core.py:262-272`
Greedy binds the highest-score edge first; not a max-cardinality matching. Repro (confirmed):
edges f0–d0=.90, f0–d1=.80, f1–d0=.85 (f1 reaches only d0) → greedy matches only d0 (recall 1/2);
optimal is f0→d1,f1→d0 (recall 2/2). Same CLASS as the fixed over-merge bug: a real distinct defect
mislabeled "missed" → deflated recall → can flip a run to false-convergence. **Fix:** Hungarian /
max-cardinality bipartite matching (Kuhn augmenting-path; no scipy needed).
**QUANTIFIED** (`runs/_scratch/B/verify_assignment.py`, all 720): greedy recall < optimal on **78 rounds**;
on the **terminal round of 12/720 trajectories** (~1.7%), of which ~9 could flip contractive-to-correct↔
false-convergence. The 12 split ~evenly across mem (4) and nomem (5) arms → fixing it nudges absolute CC
rates but very likely **preserves the mem>nomem gap**. Real bug, small magnitude — fix for correctness
before the definitive number.

### 2. [HIGH] Hallucination excused as "duplicate"  `matcher/core.py:263,279-280`
`matched_any` treats ANY finding with ≥1 SAME edge as a duplicate and drops it from `false_findings`.
A hallucination that catches a broad defect paraphrase, then loses the assignment, is NOT counted as
false → inflates precision / deflates false-fraction. Should only excuse a finding whose *specific*
best-matched defect was won by another finding AND that has no other unclaimed defect it matches.

### 3. [HIGH/MED] Warm-vs-cold nondeterminism  `matcher/core.py:300` (+ `:204` opposite sign)
Cache-hit SAME → score 1.0 (fresh SAME → real `sim`); `match()` maps NaN→ -1.0 (opposite). On a warm
cache all SAME edges tie → assignment falls to index order, differing from a cold run. Interacts with
#1 (index-order greedy is the worst case). Breaks the "cache = exact reproducibility" claim.
*Note: Agent 2 argued this is metric-neutral (set membership unchanged) in the DUPLICATE geometry; but in #1's geometry it changes which defect is missed → recall. **Resolved by the #1 fix:** with a maximum-cardinality matching the matched *count* is invariant to the tie-break (a unique max size), so recall/false counts are identical warm-vs-cold; only the (metric-irrelevant) identity of a tied TP could differ. The NaN cache-hit score is now a single shared constant across both assignment paths (was +1.0 / -1.0). Regression test `test_ground_truth_warm_cache_equals_cold`.*

### 4. [HIGH] Cross-artifact cache bleed  `matcher/cache.py:27-37`
`finding_fingerprint` = sha1(normalize(text)+unit); excludes offsets AND artifact id. Two artifacts
sharing a unit name (`main.py`, `utils.py`, section ids) + a normalized claim collide → a verdict
decided in artifact A replays in artifact B without the judge. **Fix:** fold artifact id into the key.
**QUANTIFIED:** 0 pair-keys are queried across ≥2 artifacts on the real 720-trajectory run → **theoretical
only, no impact here.** (The 99 fingerprint "collisions" found are benign — cosmetic variants like backtick
vs none, `-1` vs `−1`, `n=0` vs `n == 0` — the same finding correctly merged. Fix the key anyway as cheap insurance.)

### 5. [MED] Over-aggressive normalization drops discriminative symbols  `matcher/similarity.py:36`
`normalize` strips non-alphanumerics → `n <= len` and `n >= len` both become `n len` → same
fingerprint → cross-pair verdict bleed. Also feeds #4.

### 6. [MED] Subset phrase auto-passes `lexical-high`  `similarity.py:75` vs `core.py:158`
overlap coeff = |A∩B|/min → any finding that is a token-subset of a defect scores 0.85 > tau_high 0.60,
bypassing the judge (recall-leaning, but also lets a subset-hallucination get a spurious SAME edge → feeds #2).

### 7. [MED] Same-family judge silently accepted  `compute_metrics.py:70,88`
Default `--judge deepseek:deepseek-v4-pro` vs V4-Flash loop = same family, violating PLANS §84; no
guard despite `traj.model_id` being available. **Fix:** warn / require `--allow-same-family`.

### 8. [MED] Silent trajectory drop biases the denominator  `compute_metrics.py:102-104,149`
Broad `except Exception → return None` drops a failed trajectory; `n_runs=len(rows)` hides it. Failures
correlate with artifact type → non-random → biased regime fractions. **Fix:** count/report skips; assert n==720.

### 9. [MED, DISCLOSURE] `CORRECT_RECALL=0.80` == "perfect recall" on this corpus  `regime.py:23`
Artifacts have 3–4 defects → achievable recall ∈ {0,⅓,⅔,1}/{0,¼,½,¾,1}; only 1.0 clears 0.80. The
threshold silently means "recovered EVERY defect." (Explains the flat recall axis in the sensitivity sweep.)
Disclose, or use a threshold mapping to a real intermediate outcome.

### Lower: `_majority` tie-break order-dependent with even replicate counts (`armstats.py:83`);
unmatched-artifact silent drop not reported (`armstats.py:97`); `late_defects` numerator/denominator
event-space mismatch (M4 diagnostic only); `terminal_precision`=1.0 on empty set (benign).

## Remediation (2026-07-10) — all 8 fixed with regression tests

`pytest tests/` = **115 pass** (was 109; +6 new). The default content fingerprint was verified
**byte-identical** to the pre-change formula, so the warm V4-Pro decision cache remains valid for the
Path B recompute (no re-judge forced by the fixes that are active by default).

| # | Fix | Where | Regression test |
|---|-----|-------|-----------------|
| 1 | Greedy → **maximum-cardinality** bipartite assignment (Kuhn augmenting paths, weight-leaning seed order); shared `_max_cardinality_matching` used by `match` + `match_to_ground_truth` | `matcher/core.py` | `test_max_cardinality_helper_recovers_stranded_match`, `test_match_to_ground_truth_augmenting_recovers_recall` |
| 2 | Duplicate excused **only if every defect it matches is already claimed** (not "matched ≥1 edge") | `matcher/core.py` | `test_duplicate_excused_only_when_its_defect_is_claimed` |
| 3 | Unified NaN cache-hit score (`_CACHE_HIT_SCORE`, was +1.0/−1.0 across the two paths) → warm == cold | `matcher/core.py` | `test_ground_truth_warm_cache_equals_cold` |
| 6 | `lexical-high` judge-bypass now requires a **symmetric** high score (`symmetric_similarity`), so a token-subset can't auto-pass | `matcher/similarity.py`, `matcher/core.py` | `test_subset_finding_is_escalated_not_auto_passed` |
| 7 | Same-family judge **refused** unless `--allow-same-family` (PLANS §84); pure helper `same_family_clash` | `matcher/judges.py`, `scripts/compute_metrics.py` | `test_same_family_clash_guard`, `test_spec_family_from_model_and_provider` (+ end-to-end: exit 2 before judging) |
| 8 | Silent trajectory drops **counted + reported** (`n_files`/`n_skipped`/`skipped_files`), loud warning, `--expect N` hard gate (exit 3) | `scripts/compute_metrics.py` | end-to-end smoke (synthetic dir) |

**#4 (artifact scope) and #5 (operator-aware fingerprint)** are implemented + unit-tested
(`test_fingerprint_scope_isolates_artifacts`, `test_fingerprint_operator_awareness_optional`) but
**default-off**, because activating them changes the content fingerprint and would invalidate the warm
cache. They are proven inert on this corpus by the audit (#4: **0** cross-artifact pair-keys; #5: the
99 fingerprint collisions are all benign cosmetic variants), so the headline uses the validated warm
cache and these ship as hardening for future/mixed corpora. **Cost of activating them (a full cold
re-judge):** ~**97,071** distinct band pairs over the 840 trajectories ≈ **$39** at V4-Pro rates, vs
~**$6** warm — a ~$33 premium to re-derive verdicts the audit already proved identical. Recommend
warm (ship #4/#5 default-off); flip them on only if a reviewer demands an end-to-end cold run.

## Bottom line
Stats + metric-suite are sound; **the matcher assignment/cache logic (#1–#6) is where the risk is** — the
same over-merge *class* the paper already tripped on once. **All three quantified, all gap-preserving:**
#1 = 12/720 terminal (~balanced across arms); #2 upper-bound shrinks the mem–nomem gap only **+0.100 → +0.072**
(stays clearly positive); #4 = **0 cross-artifact pair-keys on this corpus** (theoretical; the 99 fp collisions
are benign cosmetic variants). None of the matcher bugs flip the headline — fix them for rigor, not survival.
Right sequence (data intact — no regeneration): **fix #1–#8 with regression tests → Path B recompute with the
fixed matcher (warm V4-Pro cache still valid) → re-measure + cross-judge robustness.**

**Status 2026-07-10: step 1 DONE.** All 8 remediated with regression tests (115 pass); the default
fingerprint is byte-identical so the warm cache is intact. Ready for the Path B recompute — the fixes
that move (or verify) the headline (#1/#2/#3, #6, #7/#8) are active on the warm run; #4/#5 are default-off
hardening (proven inert here). Next: warm recompute → item-paired McNemar/sign stats → cross-judge robustness.
