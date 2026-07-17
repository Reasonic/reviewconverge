# Human labeling — are these two findings the SAME issue?

Open `kappa_worksheet.csv` in a spreadsheet. For each row, read finding A and finding B and decide whether a competent reviewer would consider them **the same underlying issue** (even if worded differently) or **different** issues. Put `same` or `different` in the `label` column. Leave blank to skip.

- Same = one and the same defect, regardless of wording/granularity.
- Different = distinct defects, even if they sit in the same place.

The `id` column is an opaque row id — ignore it; judge only the two findings. The oracle's answer is withheld (held out in `kappa_key.csv`) so your labels stay independent. When done, run `python scripts/compute_kappa.py --worksheet matcher_gold/kappa_worksheet.csv --key matcher_gold/kappa_key.csv` to score Cohen's κ against the oracle labels.
