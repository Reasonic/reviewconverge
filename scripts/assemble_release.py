#!/usr/bin/env python3
"""Assemble a tracked `release/` set so every reported number and figure reproduces
from the artifact (audit R2-M8: the metrics JSONs figures depend on were git-ignored).

Copies the campaign metrics + sensitivity outputs from the git-ignored scratch area into
a version-controlled `release/metrics/`, includes a small sample of raw trajectories, and
writes a manifest with sha256s + a reproduction guide. The large decision cache and the
full 840-trajectory corpus are named for Zenodo (too big for git).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = ROOT / "runs" / "_scratch"
B = SCRATCH / "B"
REL = ROOT / "release"

# metric/sensitivity files that back a reported number or figure -> release/metrics/
METRICS = {
    "pathB_metrics.json": B / "pathB_metrics.json",                 # 840-run campaign (RQ1/RQ2)
    "gpt_reviewer_metrics.json": B / "gpt_reviewer_metrics.json",   # GPT-5.5 reviewer replication
    "analysis_v05.json": B / "analysis_v05.json",                   # all v0.5 recomputes
    "gray_sensitivity.json": B / "gray_sensitivity.json",           # 3-policy gray-zone sensitivity
    "contamination_probe.json": B / "contamination_probe.json",     # memorization probe (S7)
    "stats_appendix.md": B / "stats_appendix.md",                   # Appendix A table
}
# a few raw trajectories so the format is inspectable without the full (large) set
SAMPLE_ARMS = {"mem": 2, "nomem": 2, "ledger": 1, "structured-memory": 1}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def main():
    (REL / "metrics").mkdir(parents=True, exist_ok=True)
    (REL / "trajectories_sample").mkdir(parents=True, exist_ok=True)

    manifest = {"metrics": {}, "trajectories_sample": [], "missing": []}
    for name, src in METRICS.items():
        if not src.exists():
            manifest["missing"].append(name)
            continue
        dst = REL / "metrics" / name
        shutil.copy2(src, dst)
        manifest["metrics"][name] = {"bytes": dst.stat().st_size, "sha256": sha256(dst)}

    for arm, k in SAMPLE_ARMS.items():
        d = SCRATCH / "loops" / arm
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json"))[:k]:
            dst = REL / "trajectories_sample" / f.name
            shutil.copy2(f, dst)
            manifest["trajectories_sample"].append(
                {"file": f.name, "bytes": dst.stat().st_size, "sha256": sha256(dst)})

    (REL / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")

    readme = f"""# ReviewConverge — release artifact

This directory holds the data backing every reported number and figure, version-
controlled so results reproduce without re-running the (paid) campaign.

## Contents
- `metrics/` — the campaign + sensitivity outputs:
  - `pathB_metrics.json` — 840 six-round trajectories, per-run metrics + regimes (RQ1, RQ2).
  - `gpt_reviewer_metrics.json` — 360-trajectory GPT-5.5 *reviewer* replication.
  - `analysis_v05.json` — every v0.5 recompute (both estimands, ff sweep, CIs/TOST, P(FC|stab), contamination rate).
  - `gray_sensitivity.json` — 3-policy gray-zone sensitivity (positional / semantic / none).
  - `contamination_probe.json` — reviewer memorization probe (§7).
  - `stats_appendix.md` — Appendix A (16 tests, Holm-Bonferroni).
- `trajectories_sample/` — {sum(SAMPLE_ARMS.values())} raw trajectory JSONs (format sample).
- `MANIFEST.json` — sha256 of every file above.

## Reproduce the numbers (no API calls)
From `reviewconverge/` (metrics recompute from the frozen decision cache — see Zenodo below):
```
python scripts/stats_appendix.py            # -> Appendix A table
python runs/_scratch/B/analysis_v05.py      # -> all v0.5 numbers (uses pathB_metrics.json)
```
Regime rates, McNemar/sign tests, thresholds, and CIs are pure functions of the metrics
JSONs here; no model calls are needed to reproduce the paper's statistics.

## On Zenodo (too large for git) — ⟨Zenodo DOI⟩
- `pathB_warm_v4pro.json` — the frozen V4-Pro decision cache (~7.5 MB, 157k verdicts): replays
  every finding-equivalence verdict so the *judged* pipeline reruns deterministically, no API.
- the full 840 raw trajectories + transcripts, the GPT-5.5 reviewer trajectories, and (when
  complete) the GPT-5.5 primary re-judge cache.
- the finding-equivalence gold set + blinded κ worksheet + held-out key.

## Code
The corpus (`corpus/`, frozen `MANIFEST.sha256`), matcher, harness, metric suite, and all
scripts are in this repository (MIT for code, CC-BY-4.0 for the corpus data).
Regenerate figures: `python paper/figures/make_figures.py` (reads the metrics here).
"""
    (REL / "README.md").write_text(readme)
    total = sum(m["bytes"] for m in manifest["metrics"].values())
    print(f"release/ assembled: {len(manifest['metrics'])} metrics files "
          f"({total/1e6:.1f} MB) + {len(manifest['trajectories_sample'])} sample trajectories")
    if manifest["missing"]:
        print(f"  MISSING (not yet generated): {manifest['missing']}")
    print(f"  wrote {REL/'README.md'}, {REL/'MANIFEST.json'}")


if __name__ == "__main__":
    main()
