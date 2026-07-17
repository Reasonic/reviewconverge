#!/usr/bin/env python3
"""Run the iterative-review loop over corpus artifacts and log trajectories (M2).

Each run produces a ``LoopResult`` (per-round finding-sets + raw transcripts) as
JSON, the input the M3 metric suite consumes. The loop reviews the FROZEN artifact
(never edited between rounds).

Usage::

    python scripts/run_loop.py --reviewer deepseek:deepseek-v4-flash \\
        --item code-0001 --rounds 6 --memory
    python scripts/run_loop.py --limit 5 --no-memory --config-id single-nomem

Loop models run at deployment defaults (no temperature). Keys come from a
git-ignored .env (see reviewconverge.config).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.config import load_dotenv  # noqa: E402
from reviewconverge.corpus import load_corpus  # noqa: E402
from reviewconverge.harness import FindingExtractor, LoopConfig, ReviewLoop  # noqa: E402
from reviewconverge.matcher.judges import JudgeConfigError, build_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _diff_filename(diff_text: str) -> str:
    for line in diff_text.splitlines():
        m = re.match(r"\+\+\+ b/(.+)", line)
        if m:
            return m.group(1).strip()
        m = re.match(r"diff --git a/\S+ b/(\S+)", line)
        if m:
            return m.group(1).strip()
    return "file"


def render_for_review(item) -> str:
    """What the reviewer sees. For code, render the numbered POST-IMAGE (with the
    filename) so the reviewer's line references align with the seeded-defect line
    scheme — reviewing a raw diff makes the loop count diff lines (off by the
    header offset), which breaks location matching (M2 audit). Paper/spec are raw.
    """
    if item.type != "code":
        return item.artifact_text()
    fname = _diff_filename(item.artifact_text())
    lm = item.line_map()  # post-image line number -> content
    body = "\n".join(f"{i:>4} | {lm[i]}" for i in sorted(lm))
    return (f"File under review: {fname}\n"
            f"(line numbers are shown at the left; cite them in your findings)\n\n{body}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run the iterative-review loop over corpus artifacts.")
    ap.add_argument("--reviewer", default="deepseek:deepseek-v4-flash",
                    help="reviewer model PROVIDER:MODEL (default deepseek:deepseek-v4-flash)")
    ap.add_argument("--reviewer-max-tokens", type=int, default=None,
                    help="max_completion_tokens for the reviewer (default: client default, 64). "
                         "Raise (e.g. 4096) for a REASONING reviewer such as gpt-5.5: its hidden "
                         "reasoning tokens count against this cap, so a 64-token cap returns an "
                         "empty review (finish_reason=length). Non-reasoning models are unaffected.")
    ap.add_argument("--extractor", default=None,
                    help="extractor model PROVIDER:MODEL (default: same as reviewer)")
    ap.add_argument("--rounds", type=int, default=6)
    mem = ap.add_mutually_exclusive_group()
    mem.add_argument("--memory", dest="memory", action="store_true", default=True)
    mem.add_argument("--no-memory", dest="memory", action="store_false")
    ap.add_argument("--ledger", action="store_true",
                    help="monotone evidence-ledger arm (M4, Arm 1); implies memory, single-reviewer")
    ap.add_argument("--structured-memory", action="store_true",
                    help="structured-memory control arm: ledger prompt + verbatim carry-forward "
                         "but retirement on the model's say-so (no grounds gate). Isolates the "
                         "grounded-retirement mechanism. Implies --ledger.")
    ap.add_argument("--panel-size", type=int, default=1)
    ap.add_argument("--config-id", default=None, help="defaults to single-{mem|nomem}")
    ap.add_argument("--item", default=None, help="run one artifact id (e.g. code-0001)")
    ap.add_argument("--items", default=None, help="comma-separated artifact ids to run")
    ap.add_argument("--limit", type=int, default=None, help="run the first N corpus items")
    ap.add_argument("--corpus", default=str(ROOT / "corpus"))
    ap.add_argument("--out", default=str(ROOT / "runs" / "_scratch" / "loops"))
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv[1:])

    load_dotenv()
    ledger = args.ledger or args.structured_memory  # structured-memory is a ledger variant
    grounded_retire = not args.structured_memory
    if args.structured_memory:
        default_config_id = "structured-memory"
    elif ledger:
        default_config_id = "single-ledger"
    else:
        default_config_id = f"single-{'mem' if args.memory else 'nomem'}"
    config_id = args.config_id or default_config_id
    out_dir = Path(args.out) / config_id
    out_dir.mkdir(parents=True, exist_ok=True)

    items = load_corpus(Path(args.corpus))
    if args.items:
        wanted = [s.strip() for s in args.items.split(",") if s.strip()]
        order = {w: i for i, w in enumerate(wanted)}
        items = sorted((it for it in items if it.id in order), key=lambda it: order[it.id])
        missing = set(wanted) - {it.id for it in items}
        if missing:
            print(f"error: items not found: {sorted(missing)}", file=sys.stderr)
            return 2
    elif args.item:
        items = [it for it in items if it.id == args.item]
        if not items:
            print(f"error: item {args.item!r} not found", file=sys.stderr)
            return 2
    elif args.limit:
        items = items[: args.limit]

    reviewer = build_client(args.reviewer, max_tokens=args.reviewer_max_tokens or 64)
    extractor_client = build_client(args.extractor or args.reviewer)
    config = LoopConfig(config_id=config_id, rounds=args.rounds,
                        memory=args.memory, panel_size=args.panel_size,
                        ledger=ledger, grounded_retire=grounded_retire)

    print(f"reviewer={args.reviewer}  extractor={args.extractor or args.reviewer}  "
          f"config={config_id}  rounds={args.rounds}  items={len(items)}")
    try:
        for n, it in enumerate(items, 1):
            loop = ReviewLoop(reviewer, FindingExtractor(extractor_client), config)
            run_id = f"{it.id}__{config_id}__{int(time.time())}"
            res = loop.run(render_for_review(it), it.type, it.id,
                           run_id=run_id, seed=args.seed)
            out = out_dir / f"{it.id}__{run_id}.json"
            out.write_text(json.dumps(res.to_dict(), indent=2) + "\n", encoding="utf-8")
            per_round = [len(r.findings) for r in res.trajectory.rounds]
            print(f"[{n}/{len(items)}] {it.id}: findings/round={per_round}  -> {out.name}")
    except JudgeConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"wrote trajectories to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
