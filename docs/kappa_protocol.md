# Human κ validation — blinding protocol & threats to validity

Methods-ready notes for the matcher-validation (Part C) κ. Fold into the paper's
methods + threats-to-validity sections.

## What the κ measures
The matcher's headline P/R is scored against **oracle-derived** labels (two paraphrases
of one seeded defect = *same*; two distinct defects in one artifact = *different*). To
show those oracle labels track human judgment, an expert independently labels a balanced
250-pair sample **same/different**, and we report Cohen's κ (human vs. oracle).

## Blinding protocol (what makes the label independent of the oracle)
- The sample is **balanced** (125 same / 125 different) and **stratified** (negatives
  prefer same-artifact *hard* pairs), drawn with a fixed seed (`build_kappa_sample.py --seed 0`).
- The labeling worksheet shows **only** an opaque row id (`row_0001`…) plus the two
  findings and their locations — **not the `pair_id`**. This matters: the internal
  `pair_id` bakes in `~pos~`/`~neg~` and the defect ids (e.g. `code-0007-d1~neg~code-0007-d2`),
  which would let a labeler read the answer off the id without reading the findings.
  The `id → pair_id` map is written to a **held-out key** (`kappa_key.csv`) used only
  by the scorer (`compute_kappa.py --key`), never shown to the labeler.
- The labeler judges each row purely on the two findings, applying: *same* = one and the
  same defect however worded; *different* = distinct defects even if co-located.

> Provenance note: an earlier worksheet exposed the `pair_id` column (the answer was
> readable from the id). It was caught during audit and the generator was fixed to emit
> opaque ids + a held-out key; the released worksheet contains no label-revealing field.

## Result
- **Cohen's κ = 1.00**, raw agreement **1.00** over all **250** pairs
  (`AGREEMENT_human.md`), i.e. the expert reproduced every oracle label from the findings
  alone. This clears the pre-registered κ ≥ 0.80 bar.

## Threats to validity (disclose, don't hide)
1. **Annotator = corpus author.** The labeler helped define the seeded defects, so κ=1.0
   is better read as **expert-reproducibility / self-consistency of the oracle** than as
   *independent* inter-annotator agreement. The gold-standard strengthening is a **second,
   independent annotator** (who did not build the corpus) on the same blinded worksheet
   (`kappa_worksheet_blind_blank.csv` is provided for exactly this). Reported as future work.
2. **Sample, not census.** 250 of the full gold set; balanced + hard-negative-stratified
   to avoid an easy-pair inflation.

## Artifacts
- `matcher_gold/kappa_worksheet_blind.csv` — the labeled (blinded) worksheet.
- `matcher_gold/kappa_worksheet_blind_blank.csv` — blank, for an independent annotator.
- `matcher_gold/kappa_key.csv` — held-out `id → pair_id` (the answer key; not for labelers).
- `matcher_gold/AGREEMENT_human.md` — the scored κ.
- Score with: `python scripts/compute_kappa.py --worksheet matcher_gold/kappa_worksheet_blind.csv --key matcher_gold/kappa_key.csv`
