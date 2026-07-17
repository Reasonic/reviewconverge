# Probe non-oracle finding adjudication (measuring ρ)

**Why.** The realistic-scale probe's terminal-F1 *reversal* (memory 0.76 vs no-memory 0.85) is scored
against the 41 **seeded** defects only. Memory's terminal sets retain **~3× more non-oracle findings**
than no-memory's (70 vs 25 occurrences; 2.33 vs 0.83 per run). If some of those retained findings are
**genuinely real but unseeded**, seeded-only scoring penalizes memory differentially — in exactly the
reversal's direction. This adjudication measures **ρ = the fraction of retained non-oracle findings that
are real**, per arm, so the reversal can be corrected and settled (real cost vs oracle artifact).

The −0.089 gap **attenuates to the noise band at ρ ≈ 0.5 and vanishes at ρ ≈ 0.67** (paper §5, v0.14).

## Who should do it
Ideally the same non-author reviewer who does the on-distribution matcher labeling (M2), or any competent
engineer — it is a judgment about the code, not about the paper. Author-adjudication is acceptable if
disclosed (the seeds were already author-audited, §3.2).

## Steps
1. Open **`NONORACLE_ADJUDICATION.html`** in a browser (self-contained; module source is embedded per card).
2. For each retained non-oracle finding, pick one: **Real** (a genuine unseeded defect in the module),
   **False positive** (hallucination / non-issue), or **Unsure**. Add a note if useful. Verdicts autosave
   to the browser; the running occurrence-weighted ρ is shown in the header.
3. When done, click **⬇ Export result** → `nonoracle_adjudication_result.json`.
4. Score it:
   ```
   python scripts/score_nonoracle_adjudication.py nonoracle_adjudication_result.json
   ```
   → per-arm ρ and the ρ-corrected mem−nomem F1 gap, with a REVERSAL SURVIVES / DISSOLVES / FLIPS verdict.

## Provenance / reproducing the worksheet
77 unique findings (54 memory-arm + 23 no-memory-arm), covering all 70 mem + 25 nomem terminal non-oracle
finding occurrences. Rebuild offline from the released trajectories with the frozen probe decision cache
(deterministic; self-checks the 70/25 split against the published metrics):
```
python scripts/probe_nonoracle_adjudication.py \
    --traj probe_results/trajectories.tar.gz \
    --cache <probe judge cache> \
    --out corpus_probe/NONORACLE_ADJUDICATION.html \
    --manifest corpus_probe/nonoracle_worksheet.json
```
`nonoracle_worksheet.json` is the machine-readable worksheet (finding texts + module + arm + occurrence
weight; no answer key — this is a judgment task, not a keyed test).
