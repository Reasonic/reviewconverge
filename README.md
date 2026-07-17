# ReviewConverge

**A convergence benchmark and workflow standard for iterative agentic review.**

Iterative review agents — an LLM (or a panel) that reviews a fixed artifact over
multiple rounds — are assumed to *improve* with iteration. They frequently do the
opposite: the **set of claimed findings churns**. Hallucinated findings appear, real
findings silently drop, the loop oscillates, or it settles on a confident-but-wrong
answer. ReviewConverge makes this measurable.

Given the per-round finding-sets of a review loop, ReviewConverge answers:

- **Is it converging, or just churning?** — churn, oscillation, distance-to-fixed-point.
- **Is the fixed point *correct*?** — precision/recall of the terminal finding-set vs. seeded ground truth (the converged-correct vs. converged-wrong split).
- **Which workflow change fixes it?** — a head-to-head comparison of interventions (evidence ledger, grounding-gated admission, decoupled propose/confirm, external-anchor recheck, calibrated stopping).

## Why you might use it

- **Benchmark your review agent.** Run your PR-review / paper-review / spec-audit loop against the seeded-defect corpus and get a convergence report.
- **Instrument your own loop.** Log finding-sets in the schema (`reviewconverge.schema`) and compute the metrics on your production logs — no corpus required.
- **Pick an intervention.** The paper's headline table ranks workflow changes by contractive-to-correct rate; each is a prompt/orchestration change, not a retrain.

## Status

🚧 **Pre-release.** This repository is scaffolding for an in-progress benchmark
(preprint targeted 2026). Corpus, harness, matcher, and metrics land at their
respective milestones — see each subdirectory's `README.md` for what is populated
and when. Nothing here is final until the corpus is frozen and hashed (see
`corpus/README.md`).

## Layout

```
reviewconverge/          # Python package
  schema.py              #   finding-record schema (the interchange format)
  harness/               #   iterative-review loop runner + per-round logging
  matcher/               #   finding-equivalence matcher + validation
  metrics/               #   metric suite + regime classifier
corpus/                  # seeded-defect corpus (code / paper / spec), frozen + hashed
matcher_gold/            # human-labeled finding-pair gold set for matcher validation
runs/                    # released run logs backing every number in the paper
docs/                    # workflow spec + one-page practitioner summary
scripts/                 # corpus build, freeze/hash, reproduction entrypoints
tests/                   # unit tests
```

## Install

```bash
pip install -e .
```

Requires Python 3.10+. API keys are read from the environment; never commit them
(see `.gitignore`).

## Reproducing the paper

Once released, every table is reproducible from `runs/` without re-spending on APIs.
See `docs/` for the full reproduction guide.

## License

- **Code** (this package, `scripts/`, `tests/`): MIT — see [LICENSE](LICENSE).
- **Data** (`corpus/`, `matcher_gold/`, `runs/`): CC-BY-4.0 — see [LICENSE-DATA](LICENSE-DATA).

## Citation

See [CITATION.cff](CITATION.cff). A preprint reference will be added on release.

## Limitations

ReviewConverge certifies review-loop *dynamics* against **seeded** ground truth — it
measures whether a loop converges cleanly to the defects we planted, not real-world
recall on arbitrary artifacts. A system can score well here and still miss real bugs.
Public benchmarks also invite overfitting; the corpus ships with a documented
construction recipe so fresh defect sets can be regenerated. Treat scores as a
measure of convergence behavior, not a certificate of review quality.
