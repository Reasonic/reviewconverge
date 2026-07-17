#!/usr/bin/env python3
"""Versioned re-freeze that fixes the STALE ``construction.proposer`` note (audit R3-M5).

Every frozen ``meta.json`` still reads ``proposer: "opus-4.8 (proposed) - PENDING human
oracle confirmation"`` — a note written during construction and never updated, which
**contradicts the answer key**: all 185 defects in ``defects.json`` already carry
``confirmed: true`` (that is what let the corpus freeze in the first place). This script
replaces the stale note with an accurate description of what actually happened and
re-freezes (re-hashes ``MANIFEST.sha256``). It changes only a human-readable note; no
trajectory, cache key, or reported number depends on this field.

Default is a DRY RUN (prints the diff). Pass --apply to write + re-freeze.
The wording is deliberately conservative — it says *audited & confirmed via the
documented process*, NOT "exhaustively independently human-confirmed" (see paper §3.2).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"

OLD = "opus-4.8 (proposed) - PENDING human oracle confirmation"
NEW = ("opus-4.8 (proposed); audited & confirmed 2026-07-05 via oracle audit "
       "(validator + anchor-resolution + real/findable/unique pass, "
       "docs/oracle-audit-2026-07-05.md) with a targeted human audit of ambiguous/"
       "interacting defects and all gray zones (docs/human-audit-checklist)")


def main(argv):
    apply = "--apply" in argv[1:]
    metas = sorted(CORPUS.glob("*/*/meta.json"))
    changed = 0
    for m in metas:
        d = json.loads(m.read_text())
        prop = d.get("construction", {}).get("proposer")
        if prop == OLD:
            changed += 1
            if apply:
                d["construction"]["proposer"] = NEW
                m.write_text(json.dumps(d, indent=2) + "\n")
    print(f"{'UPDATED' if apply else 'WOULD UPDATE'} {changed}/{len(metas)} meta.json proposer notes")
    print(f"\n  OLD: {OLD}\n  NEW: {NEW}\n")
    if not apply:
        print("dry run — pass --apply to write the notes and re-freeze MANIFEST.sha256")
        return 0
    print("re-freezing MANIFEST.sha256 ...")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "freeze_corpus.py"),
                        "freeze", str(CORPUS)], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
