#!/usr/bin/env python3
"""Build the R/F/U adjudication checklist for the probe's retained NON-ORACLE terminal findings.

Motivation (paper §5, v0.14): the realistic-scale terminal-F1 *reversal* (mem 0.76 vs nomem 0.85)
is scored against the 41 seeded defects only. Memory retains ~3x more non-oracle terminal findings
(2.33 vs 0.83 per run = 70 mem / 25 nomem occurrences). If a fraction rho of those retained findings
are in fact REAL (unseeded but genuine), seeded-only scoring penalizes the memory arm differentially
and the reversal is an oracle artifact: the -0.089 gap attenuates to noise at rho~0.5 and vanishes at
rho~0.67. This tool lets a human adjudicate each retained non-oracle finding Real / False-positive /
Unsure so rho can be MEASURED (then `score_nonoracle_adjudication.py` reports the corrected gap).

Fully offline: reconstructs each finding's text by re-running the deterministic canonicalization with
the frozen probe decision cache (judge=None), so the `false:k` clusters and counts reproduce the
published metrics exactly (self-checked: 70 mem / 25 nomem terminal non-oracle findings).

Usage:
    python scripts/probe_nonoracle_adjudication.py \
        --traj probe_results/trajectories.tar.gz \
        --cache runs/_scratch/probe_campaign/judge_cache_v4pro.json \
        --out corpus_probe/NONORACLE_ADJUDICATION.html \
        --manifest corpus_probe/nonoracle_worksheet.json
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import re
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))

from reviewconverge.corpus import load_corpus  # noqa: E402
from reviewconverge.matcher.cache import DecisionCache  # noqa: E402
from reviewconverge.matcher.core import Matcher  # noqa: E402
from reviewconverge.metrics.canonical import canonicalize_trajectory  # noqa: E402
from reviewconverge.schema import Location  # noqa: E402
from scripts.compute_metrics import load_trajectory  # noqa: E402

ARM_LABEL = {"single-mem": "memory", "single-nomem": "no-memory"}


def collect(traj_root: Path, corpus_dir: Path, cache_path: Path):
    items = {it.id: it for it in load_corpus(corpus_dir)}
    cache = DecisionCache.load(cache_path) if cache_path.exists() else DecisionCache()
    matcher = Matcher(judge=None, cache=cache)  # cache-only: reproduces the judged labels offline
    # arm -> module -> list of Finding (terminal-round non-oracle occurrences)
    per = defaultdict(lambda: defaultdict(list))
    counts = defaultdict(int)
    for f in sorted(traj_root.glob("**/*.json")):
        if f.name == "metrics.json" or f.name.startswith("._") or f.name.count("__") < 2:
            continue  # skip metrics + macOS AppleDouble resource files + non-trajectory json
        try:
            traj = load_trajectory(f)
        except (UnicodeDecodeError, KeyError, json.JSONDecodeError):
            continue
        item = items.get(traj.artifact_id)
        if item is None:
            continue
        gray = [Location(**z["location"]) for z in item.known_gray_zone]
        canon = canonicalize_trajectory(traj, item.defects, matcher, gray)
        terminal = canon.rounds[-1].elements
        for eid in terminal:
            if eid.startswith("false:"):
                rep = canon.reps.get(eid)
                if rep is not None:
                    per[traj.config_id][traj.artifact_id].append(rep)
                    counts[traj.config_id] += 1
    return per, dict(counts), matcher, items


def cluster_with_counts(findings, matcher):
    """Greedy dedup within a (module, arm) group; returns [(rep, weight, members)]."""
    clusters = []
    for f in findings:
        for c in clusters:
            if matcher.same_finding(f, c[0]):
                c[1] += 1
                c[2].append(f)
                break
        else:
            clusters.append([f, 1, [f]])
    return clusters


def module_source(corpus_dir: Path, module_id: str) -> str:
    hits = [h for h in glob.glob(str(corpus_dir / "**" / module_id / "artifact.*"), recursive=True)
            if not Path(h).name.startswith("._")]
    return Path(hits[0]).read_text(encoding="utf-8", errors="replace") if hits else ""


SCRIPT = r"""
<script>
const cards = () => [...document.querySelectorAll('[data-item]')];
function collect(){
  const out = {schema:'nonoracle-adjudication-v1', items:{}};
  cards().forEach(c => {
    const sel = c.querySelector('input[type=radio]:checked');
    out.items[c.dataset.item] = {
      arm: c.dataset.arm, module: c.dataset.module, weight: +c.dataset.weight,
      verdict: sel ? sel.value : null,
      note: (c.querySelector('input[data-note]')||{}).value || ''
    };
  });
  const done = Object.values(out.items).filter(x=>x.verdict).length;
  out.progress = done + '/' + cards().length;
  return out;
}
function save(){ localStorage.setItem('nonoracle', JSON.stringify(collect())); paint(); }
function restore(){
  const raw = localStorage.getItem('nonoracle'); if(!raw) return;
  const d = JSON.parse(raw);
  cards().forEach(c => {
    const r = (d.items||{})[c.dataset.item]; if(!r) return;
    if(r.verdict){ const el = c.querySelector('input[value="'+r.verdict+'"]'); if(el) el.checked = true; }
    const n = c.querySelector('input[data-note]'); if(n && r.note) n.value = r.note;
  });
  paint();
}
function paint(){
  let real=0, fp=0, uns=0, done=0, w_real=0, w_tot=0;
  cards().forEach(c => {
    const sel = c.querySelector('input[type=radio]:checked');
    const w = +c.dataset.weight; w_tot += w;
    c.classList.remove('v-real','v-false','v-unsure');
    if(sel){ done++;
      if(sel.value==='real'){real++; w_real+=w; c.classList.add('v-real');}
      else if(sel.value==='false'){fp++; c.classList.add('v-false');}
      else {uns++; c.classList.add('v-unsure');} }
  });
  const rho = w_tot ? (w_real/w_tot) : 0;
  document.getElementById('bar').textContent =
    `adjudicated ${done}/${cards().length} · Real ${real} · False ${fp} · Unsure ${uns} · `
    + `occurrence-weighted rho(real) = ${rho.toFixed(2)}`;
}
function doExport(){
  const blob = new Blob([JSON.stringify(collect(),null,1)], {type:'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'nonoracle_adjudication_result.json'; a.click();
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('input').forEach(el => el.addEventListener('change', save));
  restore(); paint();
});
</script>
"""

STYLE = r"""
<style>
:root{color-scheme:dark}
body{background:#0d1117;color:#c9d1d9;font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:0 0 120px}
header{position:sticky;top:0;background:#161b22ee;backdrop-filter:blur(6px);border-bottom:1px solid #30363d;padding:14px 22px;z-index:9}
h1{font-size:18px;margin:0 0 4px}
.sub{color:#8b949e;font-size:12.5px;max-width:900px}
#bar{margin-top:8px;font-weight:600;color:#58a6ff}
.wrap{padding:20px 22px;max-width:1000px}
.mod{margin:26px 0 8px;font-size:15px;font-weight:700;color:#e6edf3;border-bottom:1px solid #30363d;padding-bottom:4px}
.arm{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;margin-left:8px;vertical-align:middle}
.arm.memory{background:#1f6feb33;color:#79c0ff;border:1px solid #1f6feb66}
.arm.no-memory{background:#8957e533;color:#d2a8ff;border:1px solid #8957e566}
.card{background:#161b22;border:1px solid #30363d;border-left:4px solid #6e7681;border-radius:8px;padding:12px 14px;margin:10px 0}
.card.v-real{border-left-color:#3fb950}.card.v-false{border-left-color:#f85149}.card.v-unsure{border-left-color:#d29922}
.claim{font-size:13.5px;margin-bottom:6px}
.loc{color:#8b949e;font-family:ui-monospace,Menlo,monospace;font-size:12px}
.wt{color:#8b949e;font-size:11.5px;margin-left:8px}
.choices{margin:8px 0 2px}
.choices label{margin-right:16px;cursor:pointer}
.choices b.r{color:#3fb950}.choices b.f{color:#f85149}.choices b.u{color:#d29922}
.note input{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:5px;padding:3px 6px;width:min(520px,60vw)}
details{margin-top:8px}summary{cursor:pointer;color:#58a6ff;font-size:12.5px}
pre{background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:10px;overflow:auto;font:11.5px/1.5 ui-monospace,Menlo,monospace;max-height:340px}
.zone{background:#3d2c00;outline:1px solid #9e6a03}
button{background:#238636;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer}
.fab{position:fixed;right:24px;bottom:24px;z-index:20;box-shadow:0 4px 14px #0008}
</style>
"""


def esc(s):
    return html.escape(str(s), quote=True)


def render_source(src: str, loc, module_id: str) -> str:
    lines = src.splitlines()
    lo = hi = None
    if loc is not None:
        lo, hi = getattr(loc, "start", None), getattr(loc, "end", None)
    out = []
    for i, ln in enumerate(lines, 1):
        cls = " class=zone" if (lo and hi and lo <= i <= hi) else ""
        out.append(f'<span{cls}>{i:>4}  {esc(ln)}</span>')
    return f'<details><summary>▸ source: {esc(module_id)}/artifact.py</summary><pre>' + "\n".join(out) + "</pre></details>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traj", default="probe_results/trajectories.tar.gz")
    ap.add_argument("--corpus", default="corpus_probe")
    ap.add_argument("--cache", default="runs/_scratch/probe_campaign/judge_cache_v4pro.json")
    ap.add_argument("--out", default="corpus_probe/NONORACLE_ADJUDICATION.html")
    ap.add_argument("--manifest", default="corpus_probe/nonoracle_worksheet.json")
    a = ap.parse_args()

    traj_arg = Path(a.traj)
    tmp = None
    if traj_arg.suffix in (".gz", ".tgz") or traj_arg.name.endswith(".tar.gz"):
        tmp = tempfile.mkdtemp()
        with tarfile.open(traj_arg) as t:
            t.extractall(tmp)
        traj_root = Path(tmp)
    else:
        traj_root = traj_arg

    per, counts, matcher, items = collect(traj_root, Path(a.corpus), Path(a.cache))
    print("terminal non-oracle finding occurrences per arm:", counts)
    assert counts.get("single-mem") == 70 and counts.get("single-nomem") == 25, \
        f"count mismatch vs published metrics (expected mem 70 / nomem 25): {counts}"

    # build cards + manifest
    body, manifest = [], {"schema": "nonoracle-worksheet-v1", "items": [], "occurrences": counts}
    idx = 0
    for arm in ("single-mem", "single-nomem"):
        label = ARM_LABEL[arm]
        for module_id in sorted(per[arm]):
            src = module_source(Path(a.corpus), module_id)
            clusters = cluster_with_counts(per[arm][module_id], matcher)
            body.append(f'<div class=mod>{esc(module_id)} <span class="arm {label}">{label} arm</span></div>')
            for rep, weight, _members in clusters:
                idx += 1
                iid = f"{arm}:{module_id}:{idx}"
                loc = rep.location
                loc_s = f"{loc.unit}:{loc.start}-{loc.end}" if loc else "(unlocalized)"
                name = f"v{idx}"
                body.append(
                    f'<div class=card data-item="{esc(iid)}" data-arm="{label}" '
                    f'data-module="{esc(module_id)}" data-weight="{weight}">'
                    f'<div class=claim>{esc(rep.claim)}</div>'
                    f'<div class=loc>{esc(loc_s)}<span class=wt>· appears in {weight} run(s)</span></div>'
                    f'<div class=choices>'
                    f'<label><input type=radio name="{name}" value="real"> <b class=r>Real</b> — a genuine unseeded defect</label>'
                    f'<label><input type=radio name="{name}" value="false"> <b class=f>False positive</b> — hallucination / non-issue</label>'
                    f'<label><input type=radio name="{name}" value="unsure"> <b class=u>Unsure</b></label>'
                    f'</div>'
                    f'<div class=note>notes: <input type=text data-note></div>'
                    f'{render_source(src, loc, module_id)}'
                    f'</div>')
                manifest["items"].append({"id": iid, "arm": label, "module": module_id,
                                          "weight": weight, "claim": rep.claim, "location": loc_s})

    total_unique = len(manifest["items"])
    page = (
        "<!doctype html><meta charset=utf-8>"
        "<title>ReviewConverge — non-oracle finding adjudication</title>"
        + STYLE +
        '<header><h1>Probe non-oracle finding adjudication (R/F/U)</h1>'
        '<div class=sub>For each retained <b>non-oracle</b> terminal finding (not one of the 41 seeded '
        'defects), judge whether it is a <b>Real</b> unseeded defect, a <b>False positive</b> '
        '(hallucination), or <b>Unsure</b>. This measures &rho; = fraction of retained findings that are '
        'genuinely real, per arm — settling whether the realistic-scale terminal-F1 reversal (mem 0.76 vs '
        'nomem 0.85) is real or a seeded-oracle artifact. Verdicts autosave; use Export when done, then '
        'run <code>score_nonoracle_adjudication.py</code>.</div>'
        f'<div id=bar>{total_unique} unique findings ({counts["single-mem"]} mem + '
        f'{counts["single-nomem"]} nomem occurrences)</div></header>'
        '<div class=wrap>' + "\n".join(body) + '</div>'
        '<button class=fab onclick="doExport()">⬇ Export result</button>'
        + SCRIPT)

    Path(a.out).write_text(page, encoding="utf-8")
    Path(a.manifest).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {a.out} ({total_unique} unique findings) + {a.manifest}")


if __name__ == "__main__":
    main()
