# Realistic-scale probe — results (2026-07-13)

Answers reviewers **R3-M1** (toy scale) and **R3-M2** (contamination): does the
memory→convergence effect hold on artifacts that are (a) longer/multi-function and
(b) freshly authored, hence uncontaminated (memorization 0.10 vs main corpus 0.28)?

**Design.** 10 freshly-authored Python modules (190–325 lines), 41 human-R/F/U-audited
seeded defects, frozen (`corpus_probe`, MANIFEST). mem vs nomem × 3 seeds × 6 rounds,
reviewer/extractor = DeepSeek-V4-Flash (paper default), judge = DeepSeek-V4-Pro (paper
primary; same-family, gray policy = positional). This is a **directional robustness
probe, pre-registered as underpowered** (~10 artifacts → few discordant pairs): we
report direction, effect size, and the recall distribution, not a new confirmatory p.

## Headline numbers (30 trajectories per arm)

| metric | mem | nomem | reading |
|---|---|---|---|
| **true-defect attrition events** (mean) | **0.17** | **1.37** | memory loses ~8× fewer real defects — *the mechanism* |
| terminal recall (traj mean) | 0.94 | 0.88 | recall benefit **replicates** on uncontaminated code |
| mean churn | 0.15 | 0.33 | memory stabilizes the finding set |
| late churn | 0.15 | 0.35 | " (final rounds) |
| converged-flag rate | 0.50 | 0.13 | memory converges ~4× more often |
| CC-rate (contractive-to-correct) | 0.40 | 0.10 | direction replicates |
| terminal **precision** | **0.65** | **0.84** | memory also retains false positives — *new scale nuance* |
| terminal false-fraction | 0.35 | 0.16 | " |

**CC-rate** — run-level 0.40 (mem) vs 0.10 (nomem); per-artifact-majority 4/10 vs 1/10;
McNemar exact on the per-artifact CC indicator: mem-only=3, nomem-only=0, **p=0.25**
(the smallest attainable at n=10 with 3–0 discordant — underpowered by design, as
pre-registered).

## Three findings

1. **The core mechanism replicates cleanly on uncontaminated realistic-scale code.**
   Memory prevents true-defect attrition (0.17 vs 1.37 events — ~8× fewer real findings
   dropped across rounds), which drives higher terminal recall (0.94 vs 0.88), much lower
   churn (0.15 vs 0.33), and ~4× more convergence (0.50 vs 0.13). This is the *same*
   mechanism as the main corpus, now shown on freshly-authored code the reviewer cannot
   have memorized. **The recall/convergence benefit is not a contamination artifact.**

2. **Recall is genuinely off the ceiling here** (R3-M2 answered directly). Terminal
   recall is 0.88–0.94, not ≈1.0; 7/10 (nomem) and 4/10 (mem) artifacts sit below
   ceiling. The near-ceiling recall on the short main corpus reflected its scale/simplicity;
   on longer fresh code there is real headroom — and memory still captures most of it.

3. **New scale-dependent nuance: memory's carry-forward is double-edged.** On longer
   artifacts (more surface for plausible-but-false observations) memory retains false
   positives as well as true ones, lowering terminal precision (0.65 vs 0.84) and
   producing divergent/growing sets (e.g. probe-0002 mem set sizes [4,4,5,6,6,7]). The
   short main corpus masked this because it offered little surface for false accumulation.
   **Honest caveat:** inspecting the retained non-oracle findings (e.g. probe-0002 mem:
   two trim-logic elaborations near the real defect, plus two CSV edge-case concerns)
   shows a *mix* of genuine hallucination and plausibly-real-but-unseeded issues, so the
   measured precision cost is an **upper bound** on hallucination, not a pure-hallucination
   rate.

## Framing for the paper

The probe **strengthens** the external-validity story: the central claim (memory
prevents true-defect forgetting → convergence) survives a scale + contamination stress
test, while surfacing an honest, scale-dependent precision cost that the main corpus
could not reveal. Convergence significance is not claimed at this n (directional probe).

### Proposed §5 insert (subsection: "Scale and contamination robustness")

> To test whether the memory→convergence effect is an artifact of short, potentially
> memorized artifacts, we ran an out-of-distribution probe: 10 freshly-authored modules
> (190–325 lines; 41 audited seeded defects; prefix-continuation memorization 0.10 vs the
> main corpus 0.28), scored through the identical pipeline (mem vs nomem × 3 seeds). The
> core mechanism replicates: memory reduces true-defect attrition from 1.37 to 0.17 events
> per run, raising terminal recall (0.94 vs 0.88) and convergence (CC-rate 0.40 vs 0.10;
> converged 0.50 vs 0.13) with far less churn (0.15 vs 0.33). Because recall here is
> genuinely below ceiling (7/10 nomem artifacts < 1.0), this is not a memorization artifact.
> The probe also reveals a scale-dependent limitation invisible on the short main corpus:
> memory's carry-forward retains false positives as well as true ones, lowering terminal
> precision (0.65 vs 0.84) on longer artifacts. As a ~10-artifact directional probe it is
> not powered for a convergence significance test (McNemar p=0.25); we report it for effect
> direction and the recall distribution.

## Reproduce

```
bash scripts/run_probe_campaign.sh          # 6 runs -> runs/_scratch/probe_campaign/
bash scripts/score_probe_campaign.sh        # V4-Pro judge -> metrics_*.json
python scripts/analyze_probe.py             # -> probe_analysis.json + summary
```

Raw trajectories preserved in `probe_results/trajectories.tar.gz`
(sha256 f28bba8b5196a6cfe745066900fb2dc0963bca5afcf2e7ce72e259478b3bb47f);
per-run metrics + `probe_analysis.json` in `probe_results/`.
