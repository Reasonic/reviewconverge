#!/usr/bin/env python3
"""Score human second-opinion labels against the oracle (Cohen's κ) — M1b.

Reads the human-filled ``matcher_gold/kappa_worksheet.csv`` and reports:
  - Cohen's κ between the HUMAN labels and the oracle-derived gold labels
    (the independent-source agreement a journal asks for), and
  - optionally, κ between the human and the MATCHER (with ``--cache``, using only
    cached/deterministic verdicts — no new API calls).

Writes ``matcher_gold/AGREEMENT_human.md``.

Usage::

    python scripts/compute_kappa.py                       # human vs oracle
    python scripts/compute_kappa.py --cache runs/matcher/cache_deepseek-v4-pro.json
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.matcher.cache import DecisionCache  # noqa: E402
from reviewconverge.matcher.core import Matcher  # noqa: E402
from reviewconverge.matcher.validation import cohen_kappa, load_gold_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "matcher_gold"


def parse_label(s: str):
    s = (s or "").strip().lower()
    if s in ("same", "s", "1", "yes", "y", "true"):
        return True
    if s in ("different", "diff", "d", "0", "no", "n", "false"):
        return False
    return None


def read_worksheet(path: Path) -> dict[str, bool]:
    """Map the worksheet's row key -> label. A BLINDED worksheet keys by an opaque
    ``id`` (the ``pair_id`` is held out in a separate key file so the sheet can't
    leak the answer); older sheets key by ``pair_id`` directly."""
    labels: dict[str, bool] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            lab = parse_label(row.get("label", ""))
            key = row.get("id") or row.get("pair_id")
            if lab is not None and key:
                labels[key] = lab
    return labels


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Score human labels vs oracle (kappa).")
    ap.add_argument("--worksheet", default=str(GOLD / "kappa_worksheet.csv"))
    ap.add_argument("--gold", default=str(GOLD / "pairs.jsonl"))
    ap.add_argument("--key", default=None,
                    help="held-out id->pair_id map (CSV) for a BLINDED worksheet keyed by opaque id")
    ap.add_argument("--cache", default=None, help="judge cache for human-vs-matcher kappa (no new calls)")
    args = ap.parse_args(argv[1:])

    ws = Path(args.worksheet)
    if not ws.exists():
        print(f"error: {ws} not found — run scripts/build_kappa_sample.py first", file=sys.stderr)
        return 2
    human = read_worksheet(ws)
    if not human:
        print("error: no labels found in the worksheet (fill the 'label' column with "
              "same/different)", file=sys.stderr)
        return 2

    # A blinded worksheet is keyed by opaque id; resolve id -> pair_id via the held-out key.
    if args.key:
        with open(args.key, encoding="utf-8", newline="") as fh:
            id2pid = {r["id"]: r["pair_id"] for r in csv.DictReader(fh)}
        human = {id2pid[k]: v for k, v in human.items() if k in id2pid}

    gold = {p.pair_id: p for p in load_gold_jsonl(Path(args.gold))}
    ids = [pid for pid in human if pid in gold]
    h = [human[pid] for pid in ids]
    o = [gold[pid].label for pid in ids]
    agree = sum(1 for x, y in zip(h, o) if x == y) / len(ids)
    k_oracle = cohen_kappa(h, o)

    lines = [
        "# Human second-opinion agreement (matcher validation)",
        "",
        f"Human-labeled pairs scored: **{len(ids)}** "
        f"({sum(h)} same / {len(h) - sum(h)} different by the human).",
        "",
        "## Human vs oracle-derived gold labels",
        "",
        f"- agreement: **{agree:.4f}**",
        f"- Cohen's κ: **{k_oracle:.4f}**",
    ]
    print(f"human-labeled: {len(ids)}   agreement vs oracle: {agree:.4f}   κ: {k_oracle:.4f}")

    if args.cache and Path(args.cache).exists():
        matcher = Matcher(judge=None, cache=DecisionCache.load(Path(args.cache)))
        hm, mm = [], []
        for pid in ids:
            gp = gold[pid]
            dec = matcher.decide_pair(gp.a_text, gp.a_location(), gp.b_text, gp.b_location(),
                                      use_cache=True)
            hm.append(human[pid])
            mm.append(dec.same)
        k_matcher = cohen_kappa(hm, mm)
        m_agree = sum(1 for x, y in zip(hm, mm) if x == y) / len(ids)
        lines += ["", "## Human vs matcher (cached verdicts)", "",
                  f"- agreement: **{m_agree:.4f}**", f"- Cohen's κ: **{k_matcher:.4f}**"]
        print(f"human vs matcher: agreement {m_agree:.4f}   κ: {k_matcher:.4f}")

    (GOLD / "AGREEMENT_human.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote: {GOLD / 'AGREEMENT_human.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
