# Workflow spec — how to make your review loop converge

> 🚧 Populated at M4/M5, once the intervention arms have been run and ranked.

This is the practitioner-facing deliverable: a concrete recipe for turning a
churning review loop into one that converges to a *correct* fixed point.

Planned contents:
1. **Instrument** — log per-round finding-sets in the `reviewconverge.schema`
   format; compute the metric suite on your own logs.
2. **Diagnose** — read off the regime (contractive-to-correct / oscillatory-churn /
   false-convergence / divergent).
3. **Intervene** — apply the intervention arms in the order our results support,
   each a prompt/orchestration change (no retraining):
   evidence-ledger → grounding-gated admission → decoupled propose/confirm →
   external-anchor recheck → calibrated multi-clean-pass stopping.
4. **Stop** — the calibrated stopping criterion, with its measured
   early-stop-vs-recall trade-off.

The ranking and thresholds here are filled in from `../runs/` results, not asserted.
