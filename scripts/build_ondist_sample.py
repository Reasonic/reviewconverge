#!/usr/bin/env python3
"""Build an ON-DISTRIBUTION matcher-validation sample from the live campaign (audit
R2-M1 / R1-M5 / R2-M2).

The κ = 1.00 gold set validates the matcher on oracle-*constructed* paraphrase-vs-
description pairs — never on a reviewer-generated finding. This script samples the two
campaign-pair populations the reviewers asked a *non-author human* to label, so we can
report **per-arm matcher error on the deployed distribution**:

  A. finding-vs-defect decisions — for each sampled reviewer finding, the seeded defect
     the matcher judged it to (mis)match. Human answers: does this finding report this
     defect?  (measures recall / false-finding error)
  B. nomem leave-and-return pairs — a finding present in round r and again in round r+k
     that the matcher clustered as the SAME cross-round issue (the events that drive
     nomem "churn"/"oscillation"). Human answers: same issue or not?  (measures whether
     apparent churn is real or a matcher artifact — the measurement-channel confound)

Outputs (under matcher_gold/ondist/):
  worksheet.csv     — blind: opaque row_id, text_a, text_b, empty `human_same` column,
                      shuffled; NO matcher verdict, NO provenance (label can't be read off).
  key.jsonl         — row_id -> {matcher_verdict, pair_type, arm, domain, artifact, ...}.
  README.md         — labeling instructions + the stratification manifest.

Reads the frozen trajectories + the warm V4-Pro decision cache; makes NO new API calls
(the matcher verdicts are replayed from cache). Deterministic given --seed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reviewconverge.config import load_dotenv  # noqa: E402
from reviewconverge.corpus import load_corpus  # noqa: E402
from reviewconverge.matcher.cache import DecisionCache  # noqa: E402
from reviewconverge.matcher.core import Matcher  # noqa: E402
from reviewconverge.matcher.similarity import symmetric_similarity, text_similarity  # noqa: E402
from reviewconverge.metrics import canonicalize_trajectory  # noqa: E402
from reviewconverge.schema import Finding, Location, RoundFindingSet, RunTrajectory, Severity  # noqa: E402

LOOPS = ROOT / "runs" / "_scratch" / "loops"
ARMS = {"mem": ["mem", "mem-r2", "mem-r3"], "nomem": ["nomem", "nomem-r2", "nomem-r3"]}


def _rid(*parts) -> str:
    return "r" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def load_traj(path: Path) -> RunTrajectory:
    d = json.loads(path.read_text())["trajectory"]
    rounds = []
    for r in d["rounds"]:
        fs = [Finding(id=x["id"], claim=x["claim"],
                      location=Location(**x["location"]) if x.get("location") else None,
                      severity=Severity(x.get("severity", "minor")),
                      evidence=x.get("evidence"), raw=x.get("raw")) for x in r["findings"]]
        rounds.append(RoundFindingSet(round_index=r["round_index"], findings=fs))
    return RunTrajectory(run_id=d["run_id"], artifact_id=d["artifact_id"],
                         config_id=d["config_id"], model_id=d["model_id"],
                         seed=d.get("seed"), rounds=rounds)


class Rng:
    """Tiny deterministic LCG so we don't touch Math.random-style global RNG."""
    def __init__(self, seed): self.s = seed & 0xFFFFFFFF
    def next(self):
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return self.s
    def shuffle(self, xs):
        for i in range(len(xs) - 1, 0, -1):
            j = self.next() % (i + 1)
            xs[i], xs[j] = xs[j], xs[i]
        return xs


def loc_str(loc):
    if loc is None:
        return ""
    parts = [loc.unit or ""]
    if loc.start is not None:
        parts.append(f":{loc.start}" + (f"-{loc.end}" if loc.end is not None else ""))
    return "".join(parts)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "runs/_scratch/B/pathB_warm_v4pro.json"))
    ap.add_argument("--corpus", default=str(ROOT / "corpus"))
    ap.add_argument("--out", default=str(ROOT / "matcher_gold" / "ondist"))
    ap.add_argument("--n-fd", type=int, default=120, help="finding-vs-defect pairs")
    ap.add_argument("--n-lr", type=int, default=80, help="leave-and-return pairs")
    ap.add_argument("--seed", type=int, default=20260711)
    args = ap.parse_args(argv[1:])
    load_dotenv()

    items = {it.id: it for it in load_corpus(Path(args.corpus))}
    cache = DecisionCache.load(Path(args.cache))
    matcher = Matcher(judge=None, cache=cache)  # cache-only; no API calls

    files = [(fam, p) for fam, cfgs in ARMS.items() for cfg in cfgs
             for p in sorted((LOOPS / cfg).glob("*.json"))]

    fd_pool = []   # finding-vs-defect
    lr_pool = []   # leave-and-return (nomem only)

    for fam, path in files:
        traj = load_traj(path)
        item = items[traj.artifact_id]
        defects = item.defects
        dom = item.type
        gray = [Location(**z["location"]) for z in item.known_gray_zone]

        # --- Population A: finding-vs-defect on the terminal round -----------
        term = traj.rounds[-1].findings
        gt = matcher.match_to_ground_truth(term, defects, gray_zones=gray)
        for i, f in enumerate(term):
            if i in gt.true_positives:
                d = next(d for d in defects if d.id == gt.true_positives[i])
                verdict, band = True, True
            else:
                # pair the finding with its highest-similarity defect (the near-miss)
                if not defects:
                    continue
                d = max(defects, key=lambda d: max(
                    [text_similarity(f.claim, d.description)] +
                    [text_similarity(f.claim, p) for p in (d.paraphrases or [])]))
                sim = max([text_similarity(f.claim, d.description)] +
                          [text_similarity(f.claim, p) for p in (d.paraphrases or [])])
                verdict = False
                band = 0.15 <= sim <= 0.65  # ambiguous zone worth a human eye
            fd_pool.append({"pair_type": "finding_vs_defect", "arm": fam, "domain": dom,
                            "artifact": traj.artifact_id, "run_id": traj.run_id,
                            "matcher_same": verdict, "band": bool(band),
                            "text_a": f.claim, "loc_a": loc_str(f.location),
                            "text_b": d.description, "loc_b": loc_str(d.location)})

        # --- Population B: nomem leave-and-return ----------------------------
        if fam != "nomem":
            continue
        canon = canonicalize_trajectory(traj, defects, matcher, gray)
        rounds = canon.round_sets()
        for eid, rep in canon.reps.items():
            present = [eid in rs for rs in rounds]
            # leave-and-return: present, gap, present again
            returns = any(present[a] and not present[a + 1] and
                          any(present[b] for b in range(a + 2, len(present)))
                          for a in range(len(present) - 2))
            if not returns:
                continue
            # find the two rounds bracketing a gap and their representative findings
            idxs = [k for k, p in enumerate(present) if p]
            r_first, r_last = idxs[0], idxs[-1]
            f_first = next((f for f in traj.rounds[r_first].findings
                            if symmetric_similarity(f.claim, rep.claim) > 0.5), rep)
            f_last = next((f for f in traj.rounds[r_last].findings
                           if symmetric_similarity(f.claim, rep.claim) > 0.5), rep)
            if f_first.claim == f_last.claim and r_first == r_last:
                continue
            lr_pool.append({"pair_type": "leave_and_return", "arm": fam, "domain": dom,
                            "artifact": traj.artifact_id, "run_id": traj.run_id,
                            "matcher_same": True,  # clustered as one element ⇒ matcher says SAME
                            "band": True, "element": eid,
                            "text_a": f_first.claim, "loc_a": loc_str(f_first.location),
                            "text_b": f_last.claim, "loc_b": loc_str(f_last.location)})

    # --- stratified sampling (prefer band cases; balance verdict × domain) ---
    def sample(pool, n, rng):
        strata = defaultdict(list)
        for p in pool:
            strata[(p["matcher_same"], p["domain"], p["band"])].append(p)
        for k in strata:
            rng.shuffle(strata[k])
        # round-robin over strata, band-first
        keys = sorted(strata, key=lambda k: (not k[2], k[0], k[1]))
        out, i = [], 0
        while len(out) < n and any(strata.values()):
            k = keys[i % len(keys)]
            if strata[k]:
                out.append(strata[k].pop())
            i += 1
            if i > 100000:
                break
        return out

    rng = Rng(args.seed)
    fd = sample(fd_pool, args.n_fd, rng)
    lr = sample(lr_pool, args.n_lr, rng)
    rows = fd + lr
    for r in rows:
        r["row_id"] = _rid(r["pair_type"], r["run_id"], r["text_a"][:40], r["text_b"][:40])
    # de-dup by row_id, then shuffle for blinding
    seen, uniq = set(), []
    for r in rows:
        if r["row_id"] not in seen:
            seen.add(r["row_id"]); uniq.append(r)
    rng.shuffle(uniq)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "worksheet.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row_id", "text_a", "location_a", "text_b", "location_b", "human_same (Y/N)", "notes"])
        for r in uniq:
            w.writerow([r["row_id"], r["text_a"], r["loc_a"], r["text_b"], r["loc_b"], "", ""])
    with (out / "key.jsonl").open("w") as fh:
        for r in uniq:
            fh.write(json.dumps({k: r[k] for k in
                     ("row_id", "matcher_same", "pair_type", "arm", "domain", "artifact", "run_id", "band")}) + "\n")

    # manifest
    by = defaultdict(int)
    for r in uniq:
        by[(r["pair_type"], r["arm"], r["matcher_same"])] += 1
    (out / "README.md").write_text(
        "# On-distribution matcher-validation worksheet\n\n"
        "Label each row in `worksheet.csv` (`human_same` = Y if the two texts describe the **same issue**, "
        "N otherwise). The worksheet is blind (no matcher verdict, shuffled). Then run "
        "`scripts/score_ondist.py` to compare against `key.jsonl` and report **per-arm, per-type matcher "
        "error** on the live campaign distribution.\n\n"
        "**Who should label:** a competent reviewer who did NOT author the corpus (the whole point is an "
        "independent, on-distribution check). If the corpus author labels, disclose it and treat the numbers "
        "as a floor.\n\n"
        "- `finding_vs_defect`: does text_a (a reviewer finding) report the issue in text_b (a seeded defect)?\n"
        "- `leave_and_return`: are text_a and text_b (the same finding across two nomem rounds) the same issue? "
        "If the matcher wrongly split real recurrences, nomem 'churn' is partly an artifact.\n\n"
        f"## Sample manifest ({len(uniq)} pairs)\n\n" +
        "\n".join(f"- {pt} / {arm} / matcher_same={ms}: {c}" for (pt, arm, ms), c in sorted(by.items())) +
        "\n")

    print(f"finding_vs_defect pool={len(fd_pool)} sampled={len(fd)}")
    print(f"leave_and_return pool={len(lr_pool)} sampled={len(lr)}")
    print(f"wrote {len(uniq)} unique pairs to {out}/ (worksheet.csv, key.jsonl, README.md)")
    for (pt, arm, ms), c in sorted(by.items()):
        print(f"  {pt:18} {arm:6} matcher_same={ms!s:5} n={c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
