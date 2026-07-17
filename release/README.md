# ReviewConverge — release artifact

This directory holds the data backing every reported number and figure, version-
controlled so results reproduce without re-running the (paid) campaign.

## Contents
- `metrics/` — the campaign + sensitivity outputs:
  - `pathB_metrics.json` — 840 six-round trajectories, per-run metrics + regimes (RQ1, RQ2).
  - `gpt_reviewer_metrics.json` — 360-trajectory GPT-5.5 *reviewer* replication.
  - `analysis_v05.json` — every v0.5 recompute (both estimands, ff sweep, CIs/TOST, P(FC|stab), contamination rate).
  - `gray_sensitivity.json` — 3-policy gray-zone sensitivity (positional / semantic / none).
  - `contamination_probe.json` — reviewer memorization probe (§7).
  - `stats_appendix.md` — Appendix A (16 tests, Holm-Bonferroni).
- `trajectories_sample/` — 6 raw trajectory JSONs (format sample).
- `MANIFEST.json` — sha256 of every file above.

## Reproduce the numbers (no API calls)
From `reviewconverge/` (metrics recompute from the frozen decision cache — see Zenodo below):
```
python scripts/stats_appendix.py            # -> Appendix A table
python runs/_scratch/B/analysis_v05.py      # -> all v0.5 numbers (uses pathB_metrics.json)
```
Regime rates, McNemar/sign tests, thresholds, and CIs are pure functions of the metrics
JSONs here; no model calls are needed to reproduce the paper's statistics.

## On Zenodo (too large for git) — ⟨Zenodo DOI⟩
- `pathB_warm_v4pro.json` — the frozen V4-Pro decision cache (~7.5 MB, 157k verdicts): replays
  every finding-equivalence verdict so the *judged* pipeline reruns deterministically, no API.
- the full 840 raw trajectories + transcripts, the GPT-5.5 reviewer trajectories, and (when
  complete) the GPT-5.5 primary re-judge cache.
- the finding-equivalence gold set + blinded κ worksheet + held-out key.

## Code
The corpus (`corpus/`, frozen `MANIFEST.sha256`), matcher, harness, metric suite, and all
scripts are in this repository (MIT for code, CC-BY-4.0 for the corpus data).
Regenerate figures: `python paper/figures/make_figures.py` (reads the metrics here).
