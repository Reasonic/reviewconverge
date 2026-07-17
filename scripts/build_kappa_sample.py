#!/usr/bin/env python3
"""Draw a blinded finding-pair sample for HUMAN second-opinion labeling (M1b).

The matcher's headline P/R is against *oracle-derived* labels (paraphrases of one
seeded defect = same; distinct defects = different). A journal reviewer will want
inter-rater agreement against an INDEPENDENT human source. This builds a balanced,
stratified, **blinded** sample (the oracle answer is withheld) for a human to label
same/different; ``compute_kappa.py`` then scores Cohen's κ human-vs-oracle.

The worksheet is BLINDED — keyed by an opaque ``id`` so the oracle label can't be read
off the ``pair_id`` (which bakes in ``~pos~`` / ``~neg~`` and the defect ids). The
``id -> pair_id`` map is held out for scoring.

Writes to ``matcher_gold/``:
  - ``kappa_worksheet.csv``  — open in a spreadsheet, fill the ``label`` column
    with ``same`` or ``different`` (leave blank to skip). Shows only ``id`` + the two findings.
  - ``kappa_key.csv``        — HELD-OUT ``id -> pair_id`` map. Do NOT give this to the
    labeler; ``compute_kappa.py --key`` reads it only for scoring.
  - ``kappa_sample.jsonl``   — the same blinded pairs (opaque id), machine-readable.
  - ``KAPPA_INSTRUCTIONS.md`` — how to label.

Usage::

    python scripts/build_kappa_sample.py --n 250 --seed 0
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.matcher.validation import load_gold_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "matcher_gold"


def stratified_sample(pairs, n, seed):
    """Balanced ~50/50 same/different; negatives prefer same-artifact HARD ones."""
    rng = random.Random(seed)
    pos = [p for p in pairs if p.label]
    neg = [p for p in pairs if not p.label]
    hard = [p for p in neg if "same-artifact" in p.source]
    easy = [p for p in neg if "same-artifact" not in p.source]
    rng.shuffle(pos)
    rng.shuffle(hard)
    rng.shuffle(easy)
    half = n // 2
    negs = (hard + easy)[: n - half]
    sample = pos[:half] + negs
    rng.shuffle(sample)  # interleave so same/different aren't grouped for the labeler
    return sample


def _loc(p_unit, p_start, p_end):
    if not p_unit:
        return ""
    span = ""
    if p_start is not None:
        span = f":{p_start}" + (f"-{p_end}" if p_end is not None and p_end != p_start else "")
    return f"{p_unit}{span}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build a blinded human-labeling sample for kappa.")
    ap.add_argument("--gold", default=str(GOLD / "pairs.jsonl"))
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv[1:])

    pairs = load_gold_jsonl(Path(args.gold))
    sample = stratified_sample(pairs, args.n, args.seed)

    # Opaque ids so the human sheet CANNOT leak the oracle label: the pair_id bakes in
    # ``~pos~`` / ``~neg~`` (and the defect ids), which a labeler could read off directly.
    # The id -> pair_id map is written to a HELD-OUT key used only for scoring.
    opaque = {p.pair_id: f"row_{i + 1:04d}" for i, p in enumerate(sample)}

    # machine-readable (opaque id; pair_id lives only in the held-out key)
    with (GOLD / "kappa_sample.jsonl").open("w", encoding="utf-8") as fh:
        for p in sample:
            fh.write(json.dumps({
                "id": opaque[p.pair_id],
                "a_text": p.a_text, "a_loc": _loc(p.a_unit, p.a_start, p.a_end),
                "b_text": p.b_text, "b_loc": _loc(p.b_unit, p.b_start, p.b_end),
            }, sort_keys=True) + "\n")

    # BLINDED human worksheet — opaque id, findings only, NO pair_id
    with (GOLD / "kappa_worksheet.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "finding_a", "loc_a", "finding_b", "loc_b", "label", "notes"])
        for p in sample:
            w.writerow([opaque[p.pair_id], p.a_text, _loc(p.a_unit, p.a_start, p.a_end),
                        p.b_text, _loc(p.b_unit, p.b_start, p.b_end), "", ""])

    # HELD-OUT key: id -> pair_id (pair_id encodes the oracle label). NEVER shipped to the
    # labeler; compute_kappa.py reads it via --key only to score.
    with (GOLD / "kappa_key.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pair_id"])
        for p in sample:
            w.writerow([opaque[p.pair_id], p.pair_id])

    (GOLD / "KAPPA_INSTRUCTIONS.md").write_text(
        "# Human labeling — are these two findings the SAME issue?\n\n"
        "Open `kappa_worksheet.csv` in a spreadsheet. For each row, read finding A "
        "and finding B and decide whether a competent reviewer would consider them "
        "**the same underlying issue** (even if worded differently) or **different** "
        "issues. Put `same` or `different` in the `label` column. Leave blank to skip.\n\n"
        "- Same = one and the same defect, regardless of wording/granularity.\n"
        "- Different = distinct defects, even if they sit in the same place.\n\n"
        "The `id` column is an opaque row id — ignore it; judge only the two findings. "
        "The oracle's answer is withheld (held out in `kappa_key.csv`) so your labels "
        "stay independent. When done, run `python scripts/compute_kappa.py "
        "--worksheet matcher_gold/kappa_worksheet.csv --key matcher_gold/kappa_key.csv` "
        "to score Cohen's κ against the oracle labels.\n", encoding="utf-8")

    pos = sum(1 for p in sample if p.label)
    print(f"wrote {len(sample)} blinded pairs "
          f"(oracle: {pos} same / {len(sample) - pos} different) to:")
    print(f"  {GOLD / 'kappa_worksheet.csv'}   <- fill the 'label' column (BLINDED: opaque id, no pair_id)")
    print(f"  {GOLD / 'kappa_key.csv'}          <- HELD-OUT id->pair_id key (do NOT give to the labeler)")
    print(f"  {GOLD / 'kappa_sample.jsonl'}")
    print(f"  {GOLD / 'KAPPA_INSTRUCTIONS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
