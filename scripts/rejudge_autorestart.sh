#!/usr/bin/env bash
# Self-healing runner for the #9 GPT-5.5 cross-family re-judge.
#
# GPT-5.5's endpoint intermittently WEDGES a socket on this sustained batch (connects,
# never returns); a stuck process re-wedges on retry but a FRESH process clears it (a
# direct call always works). So this driver runs compute_metrics, watches progress, and
# auto-kills+restarts on a hard wedge, accumulating decided verdicts in the shared cache
# across restarts until the run writes its full output. Decided pairs are cached (reused
# instantly on the re-stream); undecided pairs aren't, so each restart re-attempts them
# on fresh connections. --max-undecided is high so a few genuinely-stubborn pairs don't
# abort the run; a later clean pass (or the disclosure) handles them.
#
# WEDGE = cache flat AND log flat for STALL_KILL checks. The cache-hit re-stream at the
# start of each restart keeps the LOG advancing (cache flat), so it is NOT killed.
set -u
cd "$(dirname "$0")/.."
B=runs/_scratch/B
OUT=$B/metrics_gpt_primary.json
CACHE=$B/gpt_primary_cache.json
LOG=$B/gpt_primary_resume.log
DL=$B/autorestart.log
CMD=(python3 -u scripts/compute_metrics.py runs/_scratch/B/gpt_primary_input
     --judge openai:gpt-5.5 --concurrency 1 --cache "$CACHE" --out "$OUT"
     --expect 360 --max-undecided 2000)
CHECK=90            # progress poll interval (s)
STALL_KILL=4        # consecutive cache+log-flat polls -> wedge -> restart (~6 min)
MAX_RESTARTS=60

cache_n(){ python3 -c "import json;print(len(json.load(open('$CACHE'))['verdicts']))" 2>/dev/null || echo -1; }
log_n(){ grep -cE 'conv=(True|False) P/R=' "$LOG" 2>/dev/null || echo 0; }

echo "$(date -u +%FT%TZ) DRIVER START cache=$(cache_n)" >> "$DL"
for ((r=1;r<=MAX_RESTARTS;r++)); do
  [ -f "$OUT" ] && { echo "$(date -u +%T) full output present before r$r; stop" >> "$DL"; break; }
  rm -f "$OUT.partial"
  "${CMD[@]}" >> "$LOG" 2>&1 &
  pid=$!
  echo "$(date -u +%T) r$r launched pid $pid (cache=$(cache_n))" >> "$DL"
  pc=$(cache_n); pl=$(log_n); flat=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep $CHECK
    c=$(cache_n); l=$(log_n); dc=$((c-pc)); dl=$((l-pl))
    if [ "$dc" -lt 3 ] && [ "$dl" -lt 2 ]; then flat=$((flat+1)); else flat=0; fi
    echo "$(date -u +%T) r$r cache=$c(+$dc) log=$l(+$dl) flat=$flat" >> "$DL"
    pc=$c; pl=$l
    if [ "$flat" -ge "$STALL_KILL" ]; then
      echo "$(date -u +%T) r$r WEDGE (~$((STALL_KILL*CHECK/60))min no progress) -> kill+restart" >> "$DL"
      kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; break
    fi
  done
  if [ -f "$OUT" ]; then echo "$(date -u +%T) FULL OUTPUT after r$r" >> "$DL"; break; fi
  [ -f "$OUT.partial" ] && echo "$(date -u +%T) partial after r$r; restart to mop up" >> "$DL"
done
fc=$(cache_n)
echo "$(date -u +%FT%TZ) DRIVER EXIT final_cache=$fc" >> "$DL"
echo "driver done. final cache=$fc  full_output=$([ -f "$OUT" ] && echo YES || echo NO)"
tail -10 "$DL"
