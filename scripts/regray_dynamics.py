#!/usr/bin/env python3
"""Full downstream re-derivation under all three gray-zone policies (sim-round must-fix).

Extends regray_rescore.py: per policy x arm, aggregates the DYNAMICS metrics
(mean churn, oscillation degree, stabilized round) alongside CC/FC, plus the
mem-vs-nomem paired sign tests per policy. Warm cache => 0 API calls.
"""
import json, math, os, sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from reviewconverge.config import load_dotenv
from reviewconverge.corpus import load_corpus
from reviewconverge.matcher.cache import DecisionCache
from reviewconverge.matcher.core import Matcher, GrayZone
from reviewconverge.matcher.judges import LLMJudge, build_client
from reviewconverge.metrics import canonicalize_trajectory, classify_regime, compute_trajectory_metrics
from reviewconverge.schema import Finding, Location, RoundFindingSet, RunTrajectory, Severity

B = os.path.join(ROOT, "runs/_scratch/B")
LOOPS = os.path.join(ROOT, "runs/_scratch/loops")
CACHE = os.path.join(B, "gray_rescore_cache.json")
OUT = os.path.join(B, "gray_dynamics.json")
CC = "contractive-to-correct"; FC = "false-convergence"
ARMS = {"nomem": ["nomem", "nomem-r2", "nomem-r3"],
        "mem": ["mem", "mem-r2", "mem-r3"],
        "ledger": ["ledger", "ledger-r2", "ledger-r3"],
        "structured-memory": ["structured-memory", "structured-memory-r2", "structured-memory-r3"]}


def load_traj(path):
    d = json.loads(open(path).read())["trajectory"]
    rounds = []
    for r in d["rounds"]:
        fs = []
        for x in r["findings"]:
            loc = x.get("location")
            fs.append(Finding(id=x["id"], claim=x["claim"],
                              location=Location(**loc) if loc else None,
                              severity=Severity(x.get("severity", "minor")),
                              evidence=x.get("evidence"), raw=x.get("raw")))
        rounds.append(RoundFindingSet(round_index=r["round_index"], findings=fs))
    return RunTrajectory(run_id=d["run_id"], artifact_id=d["artifact_id"],
                         config_id=d["config_id"], model_id=d["model_id"],
                         seed=d.get("seed"), rounds=rounds)


def gray_list(item, policy):
    if policy == "none":
        return []
    if policy == "positional":
        return [Location(**z["location"]) for z in item.known_gray_zone]
    return [GrayZone(Location(**z["location"]), z.get("note", "")) for z in item.known_gray_zone]


def sign_test(diffs):
    pos = sum(1 for d in diffs if d > 1e-12)
    neg = sum(1 for d in diffs if d < -1e-12)
    n = pos + neg
    if n == 0:
        return 1.0, pos, neg
    k = min(pos, neg)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n)
    return p, pos, neg


load_dotenv()
items = {it.id: it for it in load_corpus(os.path.join(ROOT, "corpus"))}
cache = DecisionCache.load(CACHE) if os.path.exists(CACHE) else DecisionCache()

files = []
for fam, cfgs in ARMS.items():
    for cfg in cfgs:
        d = os.path.join(LOOPS, cfg)
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                files.append((fam, cfg, os.path.join(d, fn)))
print(f"{len(files)} trajectories", flush=True)

CONC = int(os.environ.get("REGRAY_CONC", "8"))
out = {}
for policy in ("positional", "semantic", "none"):
    matcher = Matcher(judge=LLMJudge(build_client("deepseek:deepseek-v4-pro"), parse_retries=3),
                      cache=cache, gray_policy=policy)

    def _one(rec):
        fam, cfg, path = rec
        traj = load_traj(path)
        item = items[traj.artifact_id]
        gz = gray_list(item, policy)
        canon = canonicalize_trajectory(traj, item.defects, matcher, gz)
        m = compute_trajectory_metrics(canon, {"run_id": traj.run_id, "artifact_id": traj.artifact_id,
                                               "config_id": traj.config_id, "model_id": traj.model_id})
        return fam, traj.artifact_id, {"regime": classify_regime(m), "mean_churn": m.mean_churn,
                                       "osc": m.oscillation_degree, "stab": m.stabilized_round}

    per_arm = defaultdict(list)                      # fam -> [record]
    by_art = defaultdict(lambda: defaultdict(list))  # fam -> artifact -> [record]
    done = 0
    with ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = [ex.submit(_one, rec) for rec in files]
        for fut in as_completed(futs):
            fam, art, rec = fut.result()
            per_arm[fam].append(rec)
            by_art[fam][art].append(rec)
            done += 1
            if done % 120 == 0:
                print(f"  {policy}: {done}/{len(files)}", flush=True)

    pol = {"per_arm": {}}
    for fam, recs in per_arm.items():
        pol["per_arm"][fam] = {
            "n": len(recs),
            "cc": round(sum(r["regime"] == CC for r in recs) / len(recs), 4),
            "fc": round(sum(r["regime"] == FC for r in recs) / len(recs), 4),
            "mean_churn": round(mean(r["mean_churn"] for r in recs), 4),
            "mean_osc": round(mean(r["osc"] for r in recs), 4),
            "mean_stab": round(mean(r["stab"] for r in recs), 4),
        }
    # mem-vs-nomem paired sign tests on per-artifact means
    arts = sorted(set(by_art["mem"]) & set(by_art["nomem"]))
    tests = {}
    for metric in ("mean_churn", "osc", "stab"):
        diffs = [mean(r[metric] for r in by_art["mem"][a]) - mean(r[metric] for r in by_art["nomem"][a])
                 for a in arts]
        p, pos, neg = sign_test(diffs)
        tests[metric] = {"p": round(p, 6), "pos": pos, "neg": neg, "n_arts": len(arts)}
    pol["mem_vs_nomem_sign"] = tests
    out[policy] = pol
    print(f"{policy}: {json.dumps(pol['per_arm'].get('mem'))} | tests {json.dumps(tests)}", flush=True)

cache.save(CACHE)
with open(OUT, "w") as f:
    json.dump(out, f, indent=1)
print("wrote", OUT, flush=True)
