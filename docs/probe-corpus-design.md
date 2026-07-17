# Realistic-scale probe corpus — design (2026-07-12)

**Purpose.** Answer the reviewers' external-validity critique (R3-M1 toy scale, R3-M2
contamination) with a small probe: does the memory→convergence effect hold on artifacts
that are (a) **longer / multi-unit** and (b) **freshly authored** (hence not in training
data, so terminal recall need not sit at the ceiling)? This is a *directional robustness*
probe, not a powered replication (≈10 artifacts → few discordant pairs; we report the
direction + the recall distribution, not a new p-value).

**Scope (minimal, code-only).** ~10 self-contained Python modules, **150–320 lines** each
(vs the main corpus's 23–42-line diffs), each a realistic component with several
**independent logic sites** so 3–5 defects can be seeded without cross-defect masking.

**Contamination discipline.** These are common component *types* but must be authored with
**specific, non-canonical** implementation choices (custom API shapes, particular
edge-case handling) so the exact bytes are not memorized. We then run
`scripts/contamination_probe.py` on the probe set and **require its memorization score to
be well below the main corpus** (main mean 0.28; code 0.46) — that is the evidence the
probe defeats contamination. No copying from GitHub/StdLib; no comments that reveal the
artifact is a benchmark item (no "bug here", no defect hints).

**Isolation.** Built under `corpus_probe/` — the frozen `corpus/` (tag `corpus-freeze-v1`,
MANIFEST) is **never touched**. Same on-disk format (dir-per-item: `artifact.diff` /
`meta.json` / `defects.json`), same validator, its own freeze.

## Modules (each: realistic, ~150–320 lines, ≥3 independent defect sites)
1. `token_bucket.py` — token-bucket rate limiter: refill, burst cap, per-key buckets, `allow(key, cost)`.
2. `lru_ttl_cache.py` — LRU cache with per-entry TTL + max-size eviction + `purge_expired`.
3. `retry.py` — retry executor: exponential backoff + jitter + max attempts + retry-on predicate.
4. `csv_reader.py` — CSV parser: quotes, escaped quotes, embedded newlines, type coercion.
5. `cron.py` — cron-expression parser + `next_after(dt)` (ranges, steps, lists).
6. `semver.py` — semantic-version parse, compare, and range (`^`, `~`, `x`, ranges) matching.
7. `cursor_pager.py` — opaque cursor encode/decode + stable page slicing.
8. `topo.py` — dependency resolver: topological sort + cycle detection + level assignment.
9. `rolling_stats.py` — rolling-window stats: count / mean / p95 over a time window.
10. `interval_scheduler.py` — interval overlap detection + greedy non-overlapping selection.

## Defect design (injected by the maintainer, not the authoring pass)
- 3–5 per module, each at an **independent site** (different function/branch), each
  **real** (a genuine bug), **findable from the artifact alone**, **uniquely describable**;
  2–3 paraphrases; an `anchor` substring the validator resolves at the defect line.
- Verify no cross-defect masking (a defect's stated consequence must hold given the others).
- Add `known_gray_zone` for any plausible-but-unseeded smell so it isn't scored as a
  hallucination.

## Gate before the campaign
Validator 0/0/0 · anchors resolve · **memorization << main corpus** · **USER R/F/U audit**
(non-author confirmation of the seeded defects) → then run mem-vs-nomem ×3 through the
identical pipeline.
