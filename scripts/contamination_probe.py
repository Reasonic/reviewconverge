#!/usr/bin/env python3
"""Contamination / memorization probe (audit R3-M2).

Quantifies how much the *reviewer* model has memorized the corpus artifacts, turning
the qualitative "these are public sources, so they're in training data" caveat into a
number. For each artifact we feed the reviewer the first ~55% (prefix) and ask it to
reproduce the rest verbatim, then measure similarity(continuation, held-out suffix).

Two built-in checks make this defensible:
  * the 3 hand-authored SYNTHETIC items (*-0001) are a negative control — if the probe
    works, they should reproduce far worse than the derived (public-source) items;
  * we correlate per-item memorization with the item's mean terminal recall from the
    campaign — if memorization predicts recall, that is the mechanism behind the 87.5%
    ceiling-recall we report (detection is near-free because the model can diff against
    a memorized canonical version).

Reviewer probed = deepseek-v4-flash (the main campaign reviewer). Cheap (~60 calls).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reviewconverge.config import load_dotenv  # noqa: E402
from reviewconverge.corpus import load_corpus  # noqa: E402
from reviewconverge.matcher.judges import DeepSeekClient  # noqa: E402

TYPE_WORD = {"code": "source-code file", "paper": "article", "spec": "configuration file"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def plain_text(item) -> str:
    lm = item.line_map()
    return "\n".join(lm[i] for i in sorted(lm))


def verbatim_frac(cont: str, suffix: str) -> float:
    """Fraction of held-out lines reproduced near-exactly (normalized) in the output."""
    cont_lines = {norm(l) for l in cont.splitlines() if len(norm(l)) >= 8}
    suf_lines = [norm(l) for l in suffix.splitlines() if len(norm(l)) >= 8]
    if not suf_lines:
        return float("nan")
    hit = sum(1 for l in suf_lines if l in cont_lines)
    return hit / len(suf_lines)


def probe_one(item, client, split=0.55):
    text = plain_text(item)
    lines = text.splitlines()
    if len(lines) < 6:
        return None
    k = max(2, int(len(lines) * split))
    prefix, suffix = "\n".join(lines[:k]), "\n".join(lines[k:])
    if len(norm(suffix)) < 40:
        return None
    tw = TYPE_WORD.get(item.type, "document")
    system = (f"You are shown the beginning of a publicly available {tw}. Reproduce the "
              f"continuation EXACTLY as it appears in the original source. Output only the "
              f"continuation text, with no commentary, no code fences, and no explanation.")
    try:
        cont = client.complete(system, prefix)
    except Exception as e:
        return {"id": item.id, "error": f"{type(e).__name__}: {e}"}
    ratio = SequenceMatcher(None, norm(cont), norm(suffix)).ratio()
    return {"id": item.id, "type": item.type,
            "origin": item.meta.get("source", {}).get("origin", "?"),
            "n_lines": len(lines), "suffix_lines": len(suffix.splitlines()),
            "mem_ratio": round(ratio, 4), "verbatim_frac": round(verbatim_frac(cont, suffix), 4)}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(ROOT / "corpus"))
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--recall-metrics", default=str(ROOT / "runs/_scratch/B/pathB_metrics.json"))
    ap.add_argument("--out", default=str(ROOT / "runs/_scratch/B/contamination_probe.json"))
    args = ap.parse_args(argv[1:])
    load_dotenv()

    items = load_corpus(Path(args.corpus))
    client = DeepSeekClient(model=args.model, max_tokens=1200)

    rows = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(probe_one, it, client): it.id for it in items}
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                rows.append(r)
                if "error" in r:
                    print(f"  {r['id']}: {r['error']}", file=sys.stderr)

    ok = [r for r in rows if "mem_ratio" in r]
    # per-item mean terminal recall from the campaign (memorization vs detection)
    recall_by_item = {}
    rp = Path(args.recall_metrics)
    if rp.exists():
        by = {}
        for run in json.load(open(rp))["runs"]:
            by.setdefault(run["artifact_id"], []).append(run["terminal_recall"])
        recall_by_item = {a: mean(v) for a, v in by.items()}
    for r in ok:
        r["mean_terminal_recall"] = round(recall_by_item.get(r["id"], float("nan")), 4)

    def agg(subset):
        subset = [r for r in subset if r.get("mem_ratio") is not None]
        if not subset:
            return None
        return {"n": len(subset),
                "mem_ratio": round(mean(r["mem_ratio"] for r in subset), 3),
                "verbatim_frac": round(mean(r["verbatim_frac"] for r in subset
                                            if r["verbatim_frac"] == r["verbatim_frac"]), 3)}

    summary = {
        "model": args.model, "n_items": len(ok),
        "overall": agg(ok),
        "by_domain": {d: agg([r for r in ok if r["type"] == d]) for d in ("code", "paper", "spec")},
        "by_origin": {o: agg([r for r in ok if r["origin"] == o]) for o in ("derived", "synthetic")},
    }
    # correlation: memorization vs terminal recall (Pearson, dependency-free)
    xs = [r["mem_ratio"] for r in ok if r["mean_terminal_recall"] == r["mean_terminal_recall"]]
    ys = [r["mean_terminal_recall"] for r in ok if r["mean_terminal_recall"] == r["mean_terminal_recall"]]
    if len(xs) > 2:
        mx, my = mean(xs), mean(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx = sum((x - mx) ** 2 for x in xs) ** 0.5
        sy = sum((y - my) ** 2 for y in ys) ** 0.5
        summary["pearson_mem_vs_recall"] = round(cov / (sx * sy), 3) if sx and sy else None
        summary["n_correlated"] = len(xs)

    out = {"summary": summary, "items": sorted(ok, key=lambda r: -r["mem_ratio"])}
    Path(args.out).write_text(json.dumps(out, indent=2))

    print("=" * 66)
    print(f"CONTAMINATION / MEMORIZATION PROBE — reviewer = {args.model}")
    print("=" * 66)
    o = summary["overall"]
    print(f"overall (n={o['n']}): mem_ratio {o['mem_ratio']}  verbatim_frac {o['verbatim_frac']}")
    print("\nby domain:")
    for d, a in summary["by_domain"].items():
        if a:
            print(f"  {d:6} n={a['n']:2}  mem_ratio {a['mem_ratio']}  verbatim {a['verbatim_frac']}")
    print("\nby origin (synthetic = hand-authored negative control):")
    for oo, a in summary["by_origin"].items():
        if a:
            print(f"  {oo:10} n={a['n']:2}  mem_ratio {a['mem_ratio']}  verbatim {a['verbatim_frac']}")
    if "pearson_mem_vs_recall" in summary:
        print(f"\nPearson(mem_ratio, mean_terminal_recall) = {summary['pearson_mem_vs_recall']} "
              f"(n={summary['n_correlated']})")
    print(f"\ntop-5 most-memorized: " +
          ", ".join(f"{r['id']}={r['mem_ratio']}" for r in out['items'][:5]))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
