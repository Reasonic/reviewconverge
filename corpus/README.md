# Corpus — seeded-defect artifacts

Artifacts with **constructed, human-confirmed** ground-truth defects across three
review types:

- `code/`  — code diffs with seeded bug-introducing edits
- `paper/` — paper/report excerpts with seeded factual / statistical / logic defects
- `spec/`  — specs and configs with seeded constraint violations / inconsistencies

## Ground-truth discipline (why this is trustworthy)

- Defects are **constructed, never LLM-discovered.** A frontier model may *propose*
  candidate injections, but a human confirms each defect is (a) real, (b) findable
  from the artifact alone, (c) uniquely describable.
- Every defect has an id, a location, a canonical description, and 2–3 paraphrase
  variants (the paraphrases seed `../matcher_gold/`).
- The corpus is **frozen and hashed** before any review loop runs. After the freeze,
  nothing here is edited — a drifting oracle would silently invalidate
  false-convergence detection, which is the headline result. The freeze is recorded
  as a tagged commit and a manifest of content hashes.

## Construction recipe

The documented injection recipe (per artifact type) is published alongside the
corpus so fresh defect sets can be regenerated — a mitigation against benchmark
overfitting. See `../scripts/` (build + freeze/hash entrypoints).

## Status

🚧 Empty until the M1 freeze. Populated with the frozen corpus + `MANIFEST.sha256`
at that point.
