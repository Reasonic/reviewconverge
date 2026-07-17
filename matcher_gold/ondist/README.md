# On-distribution matcher-validation worksheet

Label each row in `worksheet.csv` (`human_same` = Y if the two texts describe the **same issue**, N otherwise). The worksheet is blind (no matcher verdict, shuffled). Then run `scripts/score_ondist.py` to compare against `key.jsonl` and report **per-arm, per-type matcher error** on the live campaign distribution.

> **Note on `key.jsonl` (the answer key).** The answer key is **withheld from the public release** until the on-distribution validation is complete, so the blind stays blind for the independent annotator. It is derivable from the released oracle in any case, and will be added here once the validation lands. If you are reproducing after that point, `key.jsonl` will be present.

**Who should label:** a competent reviewer who did NOT author the corpus (the whole point is an independent, on-distribution check). If the corpus author labels, disclose it and treat the numbers as a floor.

- `finding_vs_defect`: does text_a (a reviewer finding) report the issue in text_b (a seeded defect)?
- `leave_and_return`: are text_a and text_b (the same finding across two nomem rounds) the same issue? If the matcher wrongly split real recurrences, nomem 'churn' is partly an artifact.

## Sample manifest (200 pairs)

- finding_vs_defect / mem / matcher_same=False: 56
- finding_vs_defect / mem / matcher_same=True: 22
- finding_vs_defect / nomem / matcher_same=False: 19
- finding_vs_defect / nomem / matcher_same=True: 23
- leave_and_return / nomem / matcher_same=True: 80
