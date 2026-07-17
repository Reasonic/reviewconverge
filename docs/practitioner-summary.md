# Practitioner summary (one page)

> 🚧 Populated at M5.

The TL;DR for teams shipping iterative review agents (PR review, paper review,
spec/audit loops):

- **What breaks:** review loops churn — hallucinated findings appear, real ones
  drop, loops oscillate or settle on confident-but-wrong answers. Noise drives
  reviewer fatigue and tool abandonment.
- **How to tell:** the ReviewConverge metrics (false-finding injection rate,
  true-finding attrition, oscillation, fixed-point correctness) run on your own
  round-by-round logs.
- **Which fix to adopt first:** the single highest-leverage intervention from our
  ranking, with the runner-up. (Filled in from results.)
- **Where to stop:** the calibrated stopping rule and its spend/latency saving.

One-page PDF export for sharing lands here at release.
