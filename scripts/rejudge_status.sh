#!/usr/bin/env bash
# Status of the detached #9 GPT-5.5 primary re-judge (compute_metrics on gpt_primary_input).
# Usage: bash scripts/rejudge_status.sh   (run from the reviewconverge/ dir)
cd "$(dirname "$0")/.."
# after the token-cap fix (commit 7b564ccd) the run was resumed; prefer the resume log.
LOG=runs/_scratch/B/gpt_primary.log
[ -f runs/_scratch/B/gpt_primary_resume.log ] && LOG=runs/_scratch/B/gpt_primary_resume.log
OUT=runs/_scratch/B/metrics_gpt_primary.json
EXPECT=360

pid=$(pgrep -f "compute_metrics.*gpt_primary_input" | head -1)

echo "=== #9 GPT-5.5 re-judge status ==="
if [ -f "$OUT" ]; then
  echo "STATE : ✅ DONE — output written: $OUT"
elif [ -n "$pid" ]; then
  et=$(ps -o etime= -p "$pid" | tr -d ' ')
  echo "STATE : ⏳ RUNNING (pid $pid, elapsed $et)"
else
  echo "STATE : ⚠️  NOT RUNNING and no output — died/killed before finishing (resume: re-run the same compute_metrics command; it continues from the cache)"
fi

if [ -f "$LOG" ]; then
  done=$(grep -cE "conv=(True|False) P/R=" "$LOG")
  cur=$(grep -oE "^(code|paper|spec)-[0-9]+" "$LOG" | tail -1)
  items=$(grep -oE "^(code|paper|spec)-[0-9]+" "$LOG" | sort -u | wc -l | tr -d ' ')
  pct=$(( done * 100 / EXPECT ))
  age=$(python3 -c "import os,time;print(f'{(time.time()-os.path.getmtime(\"$LOG\"))/60:.0f}')" 2>/dev/null)
  echo "PROG  : $done / $EXPECT trajectories judged (${pct}%)  ·  at $cur  ·  $items/60 items"
  echo "FRESH : log last changed ${age} min ago  (a few min = healthy; tens of min while RUNNING = likely stalled on a network read)"
fi
