#!/usr/bin/env python3
"""Collector (no API): enumerate the uncached ambiguous judge-pairs across all #9 trajectories.

GPT-5.5's endpoint wedges the long in-process judge on this sustained batch, but individual
continuous calls work. So we split the work: this pass runs the matcher's canonicalization
with a RECORDING judge (makes NO API calls) over every trajectory. Cached pairs hit the cache;
every uncached *ambiguous* pair (the ones that would go to the judge) is captured with its
(text, location) on both sides, deduped by the SAME fingerprint the cache keys on. The output
feeds judge_collected_pairs.py.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reviewconverge.config import load_dotenv  # noqa: E402
from reviewconverge.corpus import load_corpus  # noqa: E402
from reviewconverge.matcher.cache import DecisionCache, finding_fingerprint, pair_key  # noqa: E402
from reviewconverge.matcher.core import Matcher  # noqa: E402
from reviewconverge.metrics import canonicalize_trajectory  # noqa: E402
from reviewconverge.schema import Finding, Location, RoundFindingSet, RunTrajectory, Severity  # noqa: E402

B = ROOT / "runs" / "_scratch" / "B"
INPUT = B / "gpt_primary_input"
CACHE = B / "gpt_primary_cache.json"
OUT = B / "collected_pairs.jsonl"
CORPUS = ROOT / "corpus"


def load_trajectory(path: Path) -> RunTrajectory:
    t = json.loads(path.read_text(encoding="utf-8"))["trajectory"]
    rounds = []
    for r in t["rounds"]:
        fs = []
        for x in r["findings"]:
            loc = x.get("location")
            fs.append(Finding(id=x["id"], claim=x["claim"],
                              location=Location(**loc) if loc else None,
                              severity=Severity(x.get("severity", "minor")),
                              evidence=x.get("evidence"), raw=x.get("raw")))
        rounds.append(RoundFindingSet(round_index=r["round_index"], findings=fs))
    return RunTrajectory(run_id=t["run_id"], artifact_id=t["artifact_id"],
                         config_id=t["config_id"], model_id=t["model_id"],
                         seed=t.get("seed"), rounds=rounds)


def loc_dict(loc):
    return None if loc is None else {"unit": loc.unit, "start": loc.start, "end": loc.end}


class RecordingJudge:
    """Records every (uncached, ambiguous) pair the matcher asks about; never calls the API."""
    def __init__(self):
        self.pairs = {}  # pair_key -> (text_a, loc_a_dict, text_b, loc_b_dict)

    def decide(self, text_a, loc_a, text_b, loc_b):
        k = pair_key(finding_fingerprint(text_a, loc_a), finding_fingerprint(text_b, loc_b))
        if k not in self.pairs:
            self.pairs[k] = (text_a, loc_dict(loc_a), text_b, loc_dict(loc_b))
        return (False, False)  # undecided -> matcher does NOT cache it (cache untouched)


def main():
    load_dotenv()
    cache = DecisionCache.load(CACHE) if CACHE.exists() else DecisionCache()
    print(f"loaded cache: {len(cache)} verdicts")
    items = {it.id: it for it in load_corpus(CORPUS)}
    rec = RecordingJudge()
    matcher = Matcher(judge=rec, cache=cache)
    files = sorted(INPUT.glob("*.json"))
    for i, f in enumerate(files, 1):
        traj = load_trajectory(f)
        item = items.get(traj.artifact_id)
        if item is None:
            continue
        gray = [Location(**z["location"]) for z in item.known_gray_zone]
        try:
            canonicalize_trajectory(traj, item.defects, matcher, gray)
        except Exception as e:
            print(f"skip {f.name}: {type(e).__name__}: {e}", file=sys.stderr)
        if i % 60 == 0:
            print(f"  {i}/{len(files)} trajectories, {len(rec.pairs)} distinct uncached pairs")
    with open(OUT, "w", encoding="utf-8") as fh:
        for k, (ta, la, tb, lb) in rec.pairs.items():
            fh.write(json.dumps({"key": k, "text_a": ta, "loc_a": la, "text_b": tb, "loc_b": lb}) + "\n")
    print(f"collected {len(rec.pairs)} distinct uncached pairs -> {OUT}")


if __name__ == "__main__":
    main()
