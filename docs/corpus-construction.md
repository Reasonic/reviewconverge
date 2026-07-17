# Corpus construction recipe

> The documented, reproducible defect-injection procedure for the ReviewConverge
> seeded-defect corpus. Publishing this alongside the frozen corpus lets anyone
> regenerate fresh defect sets — the mitigation against benchmark overfitting.

Recipe version: **0.1.0** (matches `reviewconverge.corpus.CORPUS_FORMAT_VERSION`).

## Principles (non-negotiable)

1. **Ground truth is constructed, never LLM-discovered.** A frontier model may
   *propose* candidate injections; a human confirms each is (a) **real** (a genuine
   defect, not a style nit), (b) **findable** from the artifact alone (no outside
   knowledge required), (c) **uniquely describable** (a reviewer can name it
   distinctly from the other seeded defects). Confirmation is recorded per defect
   as `confirmed: true`.
2. **The artifact is fixed forever.** Nothing edits it between review rounds; this
   measures review *convergence*, not repair. It is also frozen+hashed before any
   loop runs — a drifting oracle silently invalidates false-convergence detection.
3. **Clean regions are part of ground truth.** Each artifact records regions
   verified defect-free, so a finding landing there is scorable as a false finding.
4. **Every defect carries 2–3 paraphrases.** These seed the matcher gold set: a
   correct matcher must call a paraphrase the *same* finding as the canonical
   description. Paraphrases must be genuinely different phrasings, not echoes.

## Per-type injection transformations

Each artifact starts from a real (or realistic) clean base, then a **documented
transformation** introduces `k` defects (k varied 3–8, mixed severities). The
`category` of each defect is drawn from the taxonomy below and stored in
`defects.json`; categories drive the per-kind metric breakdowns.

### `code/` — code diffs

Base: a small, self-contained, *correct* function/module. Transformation: apply
bug-introducing edits, presented to the reviewer as a unified diff (the reviewer
reviews the diff, as in a PR). Location `unit` = the file path inside the diff;
`start`/`end` = post-image (new-file) line numbers.

| category | transformation |
|---|---|
| `off-by-one` | shift a loop bound / slice index / range endpoint by one |
| `missing-guard` | delete a null / empty / bounds / zero-division check |
| `inverted-condition` | flip a comparison or boolean (`<`↔`>`, drop a `not`) |
| `wrong-operator` | swap an arithmetic/bitwise/logic operator (`+`↔`-`, `and`↔`or`) |
| `resource-leak` | drop a `close()`/lock release / early-return before cleanup |
| `error-swallowed` | catch an exception and ignore it (or `pass` on error) |
| `api-misuse` | swap argument order / wrong keyword / wrong return handling |
| `concurrency` | remove a lock / introduce an unsynchronized shared write |

### `paper/` — paper & report excerpts

Base: a coherent excerpt (abstract + method + a result paragraph, or similar).
Transformation: corrupt facts, statistics, or logic while keeping the prose
fluent (fluency matters — the defect must be a *content* error, not a typo).
Location `unit` = a section/paragraph id; `start`/`end` = line numbers in the
excerpt.

| category | transformation |
|---|---|
| `stat-inconsistency` | make a number not add up (wrong %, totals ≠ sum, n mismatch) |
| `citation-inversion` | state a claim that contradicts the cited source's finding |
| `unsupported-claim` | draw a conclusion the presented evidence does not support |
| `internal-contradiction` | assert two statements that cannot both be true |
| `methodology-flaw` | describe a real flaw (train/test leak, no control, p-hacking) |
| `overgeneralization` | extend a narrow result beyond its stated scope |

### `spec/` — specs & configs

Base: a valid config / spec (YAML/TOML/JSON/prose spec). Transformation: inject
constraint violations and inconsistencies. Location `unit` = a key path (e.g.
`server.timeout_ms`) or section; line numbers optional.

| category | transformation |
|---|---|
| `range-violation` | set a value outside its documented/allowed bounds |
| `cross-field-inconsistency` | make related fields conflict (min > max, %s ≠ 100) |
| `dangling-reference` | reference a name/id that is never defined |
| `type-mismatch` | give a field the wrong type (string where int required) |
| `default-conflict` | make a default contradict a stated constraint |
| `security-misconfig` | set a value that violates a stated security policy |

## On-disk format (one directory per item)

```
corpus/<type>/<type>-NNNN/
  artifact.<ext>   # the reviewed artifact — the ONLY thing a review loop sees
  meta.json        # provenance + construction record + verified-clean regions
  defects.json     # the answer key (seeded ground truth)
```

`meta.json`:
```json
{
  "id": "code-0001",
  "type": "code",
  "artifact_file": "artifact.diff",
  "title": "short human label",
  "recipe_version": "0.1.0",
  "source": {
    "origin": "synthetic|derived",
    "license": "MIT",
    "url": "https://github.com/owner/repo/blob/<sha>/path#Lnn",
    "source_ref": "<commit-sha | arXiv-id>",
    "retrieved": "2026-07-04",
    "attribution": "Author / owner name",
    "notes": ""
  },
  "construction": {"proposer": "opus-4.8 (proposed)", "transformations": ["off-by-one"]},
  "clean_regions": [{"unit": "artifact.diff", "start": 1, "end": 8, "note": "unchanged imports"}],
  "known_gray_zone": [{"location": {"unit": "artifact.diff", "start": 5, "end": 5}, "note": "pre-existing upstream smell, not a seeded defect"}],
  "defect_count": 3
}
```

`defects.json`:
```json
{
  "artifact_id": "code-0001",
  "defects": [
    {
      "id": "code-0001-d1",
      "category": "off-by-one",
      "severity": "major",
      "description": "Canonical one-sentence statement of the issue.",
      "location": {"unit": "src/window.py", "start": 42, "end": 42},
      "anchor": "> self.max_events",
      "paraphrases": ["alt phrasing 1", "alt phrasing 2", "alt phrasing 3"],
      "confirmed": false,
      "rationale": "why this is real, findable, and uniquely describable"
    }
  ]
}
```

`confirmed` starts `false` (proposed). The human oracle audit flips it to `true`
per defect; **the freeze refuses until all are `true`** (`scripts/freeze_corpus.py`).

`anchor` is a short substring that **must appear at the defect's location**. The
validator resolves the location (post-image lines for a `code` diff, raw lines for
`paper`/`spec`) and errors (`anchor-mismatch`) if the substring is absent — turning
line-number correctness into a machine check, so a mislocated defect cannot slip
into the oracle. Choose an anchor unique to the defect's line (the buggy token, a
misstated number, a dangling name).

## Real-derived sourcing (licensing + provenance)

The corpus is **real-derived**: every non-exemplar artifact starts from a real,
permissively-licensed source that we then inject defects into. This buys reviewer
credibility over synthetic artifacts, at the cost of licensing discipline.

**Allowed source licenses** (validator-enforced; a modified excerpt is a
derivative, so the source must permit redistribution of derivatives inside a
CC-BY-4.0 corpus):

- `code` / `spec`: MIT, Apache-2.0, BSD-2/3-Clause, ISC, 0BSD, Unlicense, CC0-1.0,
  PSF-2.0, Python-2.0, plus CC-BY-4.0/3.0 and public-domain (some real config
  sources — e.g. Kubernetes manifests from kubernetes/website — are CC-BY-4.0, the
  corpus's own license). **Excluded:** GPL/LGPL/MPL and any copyleft (would infect
  the corpus license).
- `paper`: **CC-BY-4.0 / CC-BY-3.0 / CC0 / public-domain only.** The default arXiv
  "non-exclusive license to distribute" does **not** grant redistribution of
  derivatives — filter arXiv to CC-BY submissions, or use open-access/PD sources.
  CC-BY-**SA** (copyleft) and CC-BY-**NC**/**ND** are all excluded.

**Required provenance** for `origin: "derived"` (validator errors if missing):
`url`, `license` (SPDX id of the *source*), and `source_ref` (a pinned commit SHA
or arXiv id — never a moving branch/tag). `retrieved` (date) and `attribution`
(author/owner) are expected too (warnings). Every derived item is also listed in
`corpus/ATTRIBUTIONS.md`.

**No-leak rule (critical):** the artifact the reviewer sees must contain **no hint
that it is a benchmark item or that defects were injected** — no "seeded",
"injected", "ReviewConverge", or answer-key comments. All such provenance lives in
`meta.json`/`defects.json`, which the loop never reads. When excerpting real code,
strip any comment that would tip off the reviewer.

**Findability for configs:** prefer defects findable by cross-referencing *within*
the artifact (a name used here but defined nowhere; two fields that conflict) over
ones needing external schema knowledge — this keeps "findable from the artifact
alone" strict. (Example: `spec-0002` uses a dangling `depends_on`, a dangling
network, and a host-port collision — all self-contained.)

**Gray-zone issues (pre-existing debatable findings).** Real artifacts carry
plausible-but-unseeded issues — upstream smells, missing rigor, style nits — that a
competent reviewer may flag. Against a seeded-only oracle these score as *false*
findings, biasing the false-finding-injection metric upward. Policy
(chosen 2026-07-05):

1. **Source-avoid**: at sourcing time, prefer real artifacts with few such issues.
2. **`known_gray_zone`**: for any that remain, record them per item in
   `meta.json.known_gray_zone` as `{"location": {...}, "note": "..."}`. The M3
   scorer **excludes** findings matching a gray-zone region (counted as neither
   true nor false), so the false-finding rate reflects genuine hallucinations only.

Gray-zone entries are *not* clean regions (a finding there is legitimate, just not
seeded) and *not* seeded defects (they are not part of ground-truth recall).

## Workflow

1. Author/collect a clean base artifact; record `source` + license in `meta.json`.
2. Apply transformations from the type's table; write `artifact.<ext>` and the
   `defects.json` records (proposer may draft; leave `confirmed: false`).
3. Record verified-clean regions in `meta.json`.
4. `python scripts/validate_corpus.py` — fix all **errors** (warnings are advisory).
5. **Human oracle audit** — for each defect confirm real / findable / uniquely
   describable, then set `confirmed: true` (M1 `AUDIT POINT`).
6. `python scripts/freeze_corpus.py freeze` — writes `MANIFEST.sha256`; then commit
   and `git tag` the freeze.
7. Post-freeze, CI runs `freeze_corpus.py verify` to guard against oracle drift.

## Balancing targets (across the whole corpus)

- ~15–25 items per type (≈60 total); k = 3–8 defects each.
- Mixed severities within and across items (not all `major`).
- Every category above represented at least a few times, so per-category metrics
  are estimable.
- Difficulty spread: some defects obvious, some subtle — the loop dynamics of
  interest (attrition, oscillation) show up on the subtle ones.
