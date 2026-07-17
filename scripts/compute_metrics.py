#!/usr/bin/env python3
"""Compute M3 convergence metrics + regime labels over logged trajectories.

For each trajectory (a ``LoopResult`` JSON from ``scripts/run_loop.py``) this
canonicalizes the finding-set trajectory against the artifact's seeded defects
using the **judged matcher** (M2-audit constraint), computes the per-run metrics,
and assigns a regime. It then reports the regime distribution overall and by
config / artifact type — the headline of the minimum preprintable unit.

Usage::

    python scripts/compute_metrics.py runs/_scratch/loops/single-mem \\
        --judge deepseek:deepseek-v4-pro --cache runs/_scratch/metric_cache.json

Use ``--no-judge`` for an offline (deterministic-matcher) dry run — NOT valid for
reported numbers (the deterministic matcher mis-scores real findings).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewconverge.config import load_dotenv  # noqa: E402
from reviewconverge.corpus import load_corpus  # noqa: E402
from reviewconverge.matcher.cache import DecisionCache  # noqa: E402
from reviewconverge.matcher.core import Matcher  # noqa: E402
from reviewconverge.matcher.judges import (  # noqa: E402
    JudgeConfigError,
    LLMJudge,
    build_client,
    same_family_clash,
)
from reviewconverge.metrics import (  # noqa: E402
    canonicalize_trajectory,
    classify_regime,
    compute_trajectory_metrics,
    regime_distribution,
)
from reviewconverge.schema import Finding, Location, RoundFindingSet, RunTrajectory, Severity  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load_trajectory(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    t = d["trajectory"]
    rounds = []
    for r in t["rounds"]:
        fs = []
        for x in r["findings"]:
            loc = x.get("location")
            fs.append(Finding(
                id=x["id"], claim=x["claim"],
                location=Location(**loc) if loc else None,
                severity=Severity(x.get("severity", "minor")),
                evidence=x.get("evidence"), raw=x.get("raw"),
            ))
        rounds.append(RoundFindingSet(round_index=r["round_index"], findings=fs))
    return RunTrajectory(run_id=t["run_id"], artifact_id=t["artifact_id"],
                         config_id=t["config_id"], model_id=t["model_id"],
                         seed=t.get("seed"), rounds=rounds)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Compute convergence metrics + regimes.")
    ap.add_argument("path", help="a trajectory JSON file or a directory of them")
    ap.add_argument("--corpus", default=str(ROOT / "corpus"))
    ap.add_argument("--judge", default="deepseek:deepseek-v4-pro")
    ap.add_argument("--no-judge", action="store_true", help="deterministic matcher (dry run only)")
    ap.add_argument("--cache", default=None, help="decision-cache JSON (reuse/persist judge verdicts)")
    ap.add_argument("--concurrency", type=int, default=8,
                    help="trajectories judged in parallel (default 8; use 1 for a GPT-5.x judge)")
    ap.add_argument("--allow-same-family", action="store_true",
                    help="permit a judge in the same model family as the loop (PLANS §84 "
                         "role separation); only for a disclosed robustness arm")
    ap.add_argument("--expect", type=int, default=None,
                    help="expected number of scored trajectories; refuse (exit 3) if the "
                         "count differs, so silently-dropped runs can't skew the denominator")
    ap.add_argument("--max-undecided", type=int, default=0,
                    help="max judge pairs left UNDECIDED (all retries failed) before the "
                         "output is treated as PARTIAL: written to <out>.partial and exit 4 "
                         "(the quota/credit-outage guard). Default 0 = strict.")
    ap.add_argument("--out", default=str(ROOT / "runs" / "_scratch" / "metrics.json"))
    args = ap.parse_args(argv[1:])

    load_dotenv()
    p = Path(args.path)
    files = sorted(p.glob("**/*.json")) if p.is_dir() else [p]
    files = [f for f in files if f.name != "metrics.json"]
    if not files:
        print(f"error: no trajectory files under {p}", file=sys.stderr)
        return 2

    items = {it.id: it for it in load_corpus(Path(args.corpus))}
    cache = DecisionCache.load(Path(args.cache)) if (args.cache and Path(args.cache).exists()) else DecisionCache()
    judge = None if args.no_judge else LLMJudge(build_client(args.judge), parse_retries=1)

    # #7: the judge family must differ from the loop model's family (PLANS §84 role
    # separation) — a same-family judge grades its own family's output. Detect it up
    # front (cheap model_id pre-scan, no API cost) and refuse unless the caller
    # explicitly opts in for a disclosed robustness arm.
    if judge is not None:
        loop_model_ids: set[str] = set()
        for f in files:
            try:
                loop_model_ids.add(
                    json.loads(f.read_text(encoding="utf-8"))["trajectory"]["model_id"])
            except Exception:
                continue
        clash = same_family_clash(args.judge, loop_model_ids)
        if clash and not args.allow_same_family:
            print(f"error: judge family '{clash}' matches the loop model family "
                  f"(PLANS §84 role separation). Use a cross-family judge (e.g. "
                  f"openai:/anthropic:), or pass --allow-same-family to run it as an "
                  f"explicitly-disclosed robustness arm.", file=sys.stderr)
            return 2
        if clash:
            print(f"WARNING: same-family judge (loop and judge are both '{clash}'); "
                  f"running as an explicitly-allowed robustness arm (PLANS §84).",
                  file=sys.stderr)

    matcher = Matcher(judge=judge, cache=cache)

    def process_one(f: Path):
        traj = load_trajectory(f)
        item = items.get(traj.artifact_id)
        if item is None:
            print(f"skip {f.name}: artifact {traj.artifact_id} not in corpus", file=sys.stderr)
            return None
        gray = [Location(**z["location"]) for z in item.known_gray_zone]
        try:
            canon = canonicalize_trajectory(traj, item.defects, matcher, gray)
        except JudgeConfigError:
            raise  # missing key -> abort the whole run
        except Exception as e:  # one bad trajectory shouldn't sink the campaign
            print(f"skip {f.name}: {type(e).__name__}: {e}", file=sys.stderr)
            return None
        m = compute_trajectory_metrics(canon, {
            "run_id": traj.run_id, "artifact_id": traj.artifact_id,
            "config_id": traj.config_id, "model_id": traj.model_id})
        regime = classify_regime(m)
        print(f"{traj.artifact_id:12} [{item.type:5}] sizes={m.set_sizes} "
              f"churn~{m.mean_churn:.2f} conv={m.converged} "
              f"P/R={m.terminal_precision:.2f}/{m.terminal_recall:.2f} -> {regime}", flush=True)
        # Per-round canonical element ids ("def:<id>" true / "false:<k>" hallucination)
        # so downstream stats can compute round-0 recall, late discovery, and distinct
        # defects found — offline, without re-judging (M4 diagnostics; Expert D).
        round_elements = [sorted(cr.elements) for cr in canon.rounds]
        return {**m.to_dict(), "regime": regime, "artifact_type": item.type,
                "config_id": traj.config_id, "round_elements": round_elements}

    rows = []
    skipped: list[str] = []  # #8: files that produced no row — must be visible, not hidden
    by_config: dict[str, list[str]] = defaultdict(list)
    by_type: dict[str, list[str]] = defaultdict(list)
    # Trajectories are independent; the shared decision cache is thread-safe and
    # V4-Pro (DeepSeek) has no back-to-back-request gotcha (use --concurrency 1 for
    # a GPT-5.x judge). Save the cache periodically so a crash loses little judging.
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
            futs = {ex.submit(process_one, f): f for f in files}
            done = 0
            for fut in as_completed(futs):
                row = fut.result()
                done += 1
                if row is not None:
                    rows.append(row)
                    by_config[row["config_id"]].append(row["regime"])
                    by_type[row["artifact_type"]].append(row["regime"])
                else:
                    skipped.append(futs[fut].name)
                if args.cache and done % 5 == 0:
                    matcher.cache.save(Path(args.cache))
    except JudgeConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        if args.cache:
            matcher.cache.save(Path(args.cache))
        return 2
    finally:
        if args.cache:
            matcher.cache.save(Path(args.cache))

    overall = regime_distribution([r["regime"] for r in rows])
    report = {
        "n_runs": len(rows),
        # #8: expose the denominator's provenance so a silent drop can't inflate rates.
        "n_files": len(files),
        "n_skipped": len(skipped),
        "skipped_files": sorted(skipped),
        "regime_distribution_overall": overall,
        "regime_distribution_by_config": {c: regime_distribution(v) for c, v in by_config.items()},
        "regime_distribution_by_type": {t: regime_distribution(v) for t, v in by_type.items()},
        "runs": rows,
    }
    # Outage guard: if the judge left too many pairs UNDECIDED (all retries failed —
    # the fingerprint of a quota/credit/endpoint outage), those pairs were scored with
    # a conservative default and NOT cached, so this report's numbers are partial. Refuse
    # to write it to the trusted --out path; write a *.partial and exit non-zero so a
    # credit-interrupted run can't be mistaken for a clean result. Re-running after the
    # outage clears is cheap (the decided verdicts are cached) and correct.
    undecided = getattr(judge, "undecided", 0) if judge is not None else 0
    out_path = Path(args.out)
    if undecided > args.max_undecided:
        out_path = out_path.with_suffix(out_path.suffix + ".partial")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("-" * 60)
    print(f"runs: {len(rows)}  (files: {len(files)}, skipped: {len(skipped)})")
    for r, frac in overall.items():
        print(f"  {r:24} {frac:.3f}")
    print(f"wrote: {out_path}")
    if judge is not None:
        print(f"judge: {judge.calls} calls, {judge.transport_errors} transport-errs, "
              f"{judge.parse_errors} parse-errs, {undecided} UNDECIDED pairs")

    if undecided > args.max_undecided:
        print(f"error: {undecided} pairs left UNDECIDED (> --max-undecided "
              f"{args.max_undecided}) — likely a judge quota/credit/endpoint outage. Those "
              f"pairs were conservatively defaulted and are NOT cached, so this report is "
              f"PARTIAL and was written to {out_path} (not {args.out}). Restore the judge's "
              f"credit/quota and RE-RUN the same command: the decided verdicts are cached, "
              f"so only the undecided pairs are re-judged.", file=sys.stderr)
        return 4

    # #8: a silent trajectory drop biases the denominator (failures correlate with
    # artifact type). Surface every skip loudly, and hard-gate on --expect.
    if skipped:
        preview = ", ".join(sorted(skipped)[:10]) + (" …" if len(skipped) > 10 else "")
        print(f"WARNING: {len(skipped)}/{len(files)} trajectories skipped and EXCLUDED "
              f"from the denominator: {preview}", file=sys.stderr)
    if args.expect is not None and len(rows) != args.expect:
        print(f"error: expected {args.expect} scored trajectories, scored {len(rows)} "
              f"({len(skipped)} skipped). Refusing (audit #8 silent-drop guard). "
              f"Report written to {args.out} for inspection.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
