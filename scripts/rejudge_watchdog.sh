#!/usr/bin/env bash
# Cost watchdog for the #9 GPT-5.5 re-judge resume. Samples progress every 10 min,
# appends a health line to watchdog.log, and EXITS EARLY (so the caller is notified
# and can intervene) on any anomaly — instead of only discovering trouble at the end
# the way the original run did (it burned ~1.7 days before the undecided guard tripped).
#
# Trips on:  full output written | real partial | process died | STALL (no cache growth
#            AND no log progress for 2 samples = hung) | cache ceiling (runaway re-judge)
#            | time cap (~10h, run should finish in ~8h; overrun => investigate).
# Healthy cache growth exonerates a slow/log-flat churny item; a legit cached-item
# re-stream advances the log — only BOTH flat is treated as a stall.
set -u
cd "$(dirname "$0")/.."
B=runs/_scratch/B
OUT=$B/metrics_gpt_primary.json
LOG=$B/gpt_primary_resume.log
HL=$B/watchdog.log
INTERVAL=600          # 10 min sample
STALL_LIMIT=2         # consecutive flat samples -> hung
MAX_SAMPLES=24        # ~4h heartbeat: exit healthy so caller reports + re-arms
CACHE_CEIL=93000      # expected end ~91.4k (78,413 cached + ~13k undecided); above = runaway

cache_n(){ python3 -c "import json;print(len(json.load(open('$B/gpt_primary_cache.json'))['verdicts']))" 2>/dev/null || echo -1; }
log_n(){ grep -cE 'conv=(True|False) P/R=' "$LOG" 2>/dev/null || echo 0; }

pc=$(cache_n); pl=$(log_n); stall=0; reason=""
echo "$(date -u +%FT%TZ) START cache=$pc log=$pl" >> "$HL"
for ((i=0;i<MAX_SAMPLES;i++)); do
  sleep $INTERVAL
  if [ -f "$OUT" ]; then reason="DONE full output written"; break; fi
  if [ -f "$OUT.partial" ]; then reason="ALERT real .partial written (undecided cap hit)"; break; fi
  if ! pgrep -f "compute_metrics.*gpt_primary_input" >/dev/null; then reason="ALERT process died"; break; fi
  c=$(cache_n); l=$(log_n); dc=$((c-pc)); dl=$((l-pl))
  echo "$(date -u +%FT%TZ) cache=$c(+$dc) log=$l(+$dl) stall=$stall" >> "$HL"
  if [ "$c" -ge "$CACHE_CEIL" ]; then reason="ALERT cache ceiling $c >= $CACHE_CEIL (runaway re-judge)"; break; fi
  if [ "$dc" -lt 5 ] && [ "$dl" -lt 2 ]; then
    stall=$((stall+1))
    if [ "$stall" -ge "$STALL_LIMIT" ]; then reason="ALERT stalled ~$((STALL_LIMIT*INTERVAL/60))min: cache+$dc log+$dl (hung on a network read?)"; break; fi
  else stall=0; fi
  pc=$c; pl=$l
done
[ -z "$reason" ] && reason="HEARTBEAT ~4h — healthy, still running (re-arm to keep watching)"
echo "$(date -u +%FT%TZ) EXIT: $reason" >> "$HL"
echo "$reason"
bash scripts/rejudge_status.sh
echo "--- last watchdog samples ---"; tail -6 "$HL"
