#!/usr/bin/env bash
# Realistic-scale probe campaign (R3-M1/M2 external-validity probe).
# mem vs nomem x 3 seeds over the FROZEN probe corpus (corpus_probe), 10 items, 6 rounds.
# Reviewer/extractor = deepseek-v4-flash (paper default). Metrics (V4-Pro judge) run separately.
#
# Resumable at (config,seed) granularity: a run whose out dir already holds >=10
# trajectories is skipped, so re-invoking after an interruption continues where it stopped.
set -u
cd "$(dirname "$0")/.."
CORPUS=corpus_probe
ROOT=runs/_scratch/probe_campaign
mkdir -p "$ROOT"
LOG="$ROOT/campaign.log"
echo "=== probe campaign start $(date -u +%FT%TZ) ===" | tee -a "$LOG"

run_one () {
  local config_flag="$1" config_name="$2" seed="$3"
  local out="$ROOT/${config_name}_s${seed}"
  local sub="$out/single-${config_name}"
  local n; n=$(ls "$sub"/*.json 2>/dev/null | wc -l | tr -d ' ')
  if [ "${n:-0}" -ge 10 ]; then
    echo "[skip] ${config_name} seed ${seed}: already ${n} trajectories" | tee -a "$LOG"
    return 0
  fi
  echo "[run ] ${config_name} seed ${seed} -> ${out}" | tee -a "$LOG"
  python3 -u scripts/run_loop.py --corpus "$CORPUS" ${config_flag} --rounds 6 --seed "${seed}" \
    --out "${out}" >> "${ROOT}/${config_name}_s${seed}.log" 2>&1
  local rc=$?
  n=$(ls "$sub"/*.json 2>/dev/null | wc -l | tr -d ' ')
  echo "[done] ${config_name} seed ${seed} rc=${rc} trajectories=${n}" | tee -a "$LOG"
}

for s in 1 2 3; do
  run_one "--memory"    "mem"   "$s"
  run_one "--no-memory" "nomem" "$s"
done
echo "=== probe campaign complete $(date -u +%FT%TZ) ===" | tee -a "$LOG"
