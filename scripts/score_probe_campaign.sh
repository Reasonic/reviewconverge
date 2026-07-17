#!/usr/bin/env bash
# Score the realistic-scale probe campaign with the paper's PRIMARY judge (V4-Pro).
# Shared decision cache across the 6 runs (a pair judged once is reused). Per-run
# metrics_<run>.json. Auto-retries on transient judge timeouts, resuming from the
# cache (undecided pairs are never cached, so a resume re-judges only those).
#
# Same-family (v4-pro judge vs v4-flash reviewer) is intentional = paper primary;
# the cross-family robustness lives in the separate GPT-5.5/Opus re-judge.
set -u
cd "$(dirname "$0")/.."
ROOT=runs/_scratch/probe_campaign
CACHE=$ROOT/judge_cache_v4pro.json
JUDGE=deepseek:deepseek-v4-pro
LOG=$ROOT/score.log
echo "=== score start $(date -u +%FT%TZ) ===" | tee -a "$LOG"
for run in mem_s1 mem_s2 mem_s3 nomem_s1 nomem_s2 nomem_s3; do
  d=$ROOT/$run
  out=$ROOT/metrics_${run}.json
  n=$(ls "$d"/*/*.json 2>/dev/null | wc -l | tr -d ' ')
  if [ -f "$out" ]; then echo "[skip] $run: metrics exist" | tee -a "$LOG"; continue; fi
  if [ "${n:-0}" -lt 10 ]; then echo "[wait] $run: only ${n:-0}/10 trajectories - not ready" | tee -a "$LOG"; continue; fi
  ok=0
  for attempt in 1 2 3 4 5 6; do
    echo "[score] $run attempt $attempt (n=$n)" | tee -a "$LOG"
    python3 -u scripts/compute_metrics.py "$d" --corpus corpus_probe --judge "$JUDGE" \
      --allow-same-family --concurrency 8 --cache "$CACHE" --expect 10 --max-undecided 0 \
      --out "$out" >> "$ROOT/score_${run}.log" 2>&1
    rc=$?
    if [ "$rc" -eq 0 ] && [ -f "$out" ]; then echo "[ok  ] $run" | tee -a "$LOG"; ok=1; break; fi
    echo "[retry] $run rc=$rc (resuming from cache)" | tee -a "$LOG"; sleep 8
  done
  [ "$ok" -eq 0 ] && echo "[FAIL] $run after retries" | tee -a "$LOG"
done
echo "=== score complete $(date -u +%FT%TZ) ===" | tee -a "$LOG"
ls -1 "$ROOT"/metrics_*.json 2>/dev/null | sed 's#.*/#  have #' | tee -a "$LOG"
