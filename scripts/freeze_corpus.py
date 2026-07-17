#!/usr/bin/env python3
"""Freeze the seeded-defect corpus, or verify a prior freeze against drift.

The frozen, hashed corpus is the oracle every ReviewConverge number trusts; a
silently-drifting oracle would invalidate false-convergence detection (the
headline result). So the freeze is a hard gate and the verify mode is the guard.
The load-bearing logic lives in ``reviewconverge.corpus``; this is a thin CLI.

Freeze (writes ``corpus/MANIFEST.sha256``)::

    python scripts/freeze_corpus.py freeze [CORPUS_ROOT]

Refuses to freeze unless (1) the corpus validates with zero errors and (2) every
seeded defect is human-confirmed (oracle hygiene, plan §4.1). After freezing,
tag the commit (e.g. ``git tag corpus-freeze-v1``).

Verify (re-hash and compare; use in CI post-freeze)::

    python scripts/freeze_corpus.py verify [CORPUS_ROOT]

Exit status is 0 on success, non-zero on any refusal / drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.corpus import (  # noqa: E402
    CorpusError,
    freeze_corpus,
    verify_manifest,
)


def do_freeze(root: Path) -> int:
    result = freeze_corpus(root)
    if result.ok:
        print(f"froze {result.n_files} files -> {result.manifest_path}")
        print("next: commit and tag this freeze, e.g. `git tag corpus-freeze-v1`.")
        return 0

    if result.errors:
        print("refusing: corpus has validation errors:", file=sys.stderr)
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)
    if result.unconfirmed:
        print(f"refusing: {len(result.unconfirmed)} defect(s) not human-confirmed "
              f"(oracle-hygiene gate). Confirm these first:", file=sys.stderr)
        for did in result.unconfirmed:
            print(f"  {did}", file=sys.stderr)
    return 1


def do_verify(root: Path) -> int:
    try:
        result = verify_manifest(root)
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if result.ok:
        print(f"ok: {result.n_files} files match MANIFEST.sha256; no drift.")
        return 0

    print("DRIFT DETECTED against the frozen manifest:", file=sys.stderr)
    for p in result.changed:
        print(f"  changed: {p}", file=sys.stderr)
    for p in result.added:
        print(f"  added:   {p}", file=sys.stderr)
    for p in result.removed:
        print(f"  removed: {p}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("freeze", "verify"):
        print(__doc__)
        return 2
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent / "corpus"
    if not root.is_dir():
        print(f"error: corpus root not found: {root}", file=sys.stderr)
        return 2
    return do_freeze(root) if argv[1] == "freeze" else do_verify(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
