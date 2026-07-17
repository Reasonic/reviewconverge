#!/usr/bin/env bash
# Unattended driver for the standalone #9 judger. Runs judge_collected_pairs.py (continuous
# fresh GPT-5.5 calls -> writes verdicts to the shared cache), and if it ever wedges (cache
# flat while alive) kills+restarts it; the judger is restartable (cached pairs are skipped),
# so it resumes. Stops when a full pass adds no new verdicts (all pairs decided or stuck).
set -u
cd "$(dirname "$0")/.."
B=runs/_scratch/B
CACHE=$B/gpt_primary_cache.json
JLOG=$B/judger.log
DL=$B/judge_driver.log
cache_n(){ python3 -c "import json;print(len(json.load(open('$CACHE'))['verdicts']))" 2>/dev/null || echo -1; }

echo "$(date -u +%FT%TZ) DRIVER START cache=$(cache_n)" >> "$DL"
prev=-1
for ((r=1;r<=40;r++)); do
  b=$(cache_n)
  if [ "$b" -eq "$prev" ]; then echo "$(date -u +%T) converged: last pass added 0 verdicts (cache=$b)" >> "$DL"; break; fi
  prev=$b
  python3 -u scripts/judge_collected_pairs.py >> "$JLOG" 2>&1 &
  pid=$!
  echo "$(date -u +%T) r$r launched pid $pid (cache=$b)" >> "$DL"
  pc=$b; flat=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 90
    c=$(cache_n)
    [ "$c" -le "$pc" ] && flat=$((flat+1)) || flat=0
    echo "$(date -u +%T) r$r cache=$c(+$((c-pc))) flat=$flat" >> "$DL"
    pc=$c
    if [ "$flat" -ge 4 ]; then
      echo "$(date -u +%T) r$r WEDGE (~6min flat) -> kill+restart" >> "$DL"
      kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; break
    fi
  done
  echo "$(date -u +%T) r$r ended (cache=$(cache_n))" >> "$DL"
done
fc=$(cache_n)
echo "$(date -u +%FT%TZ) DRIVER DONE final_cache=$fc" >> "$DL"
echo "judge driver done. final cache=$fc verdicts (target ~90,848 = 84,247 + 6,601 pairs)"
tail -10 "$DL"
