#!/usr/bin/env bash
# One-shot status for the #9 standalone-judger phase (collector + judge_driver).
# Usage: bash scripts/judge_status.sh   (run from the reviewconverge/ dir)
cd "$(dirname "$0")/.."
B=runs/_scratch/B
CACHE=$B/gpt_primary_cache.json
BASE=84287          # cache size when the judger phase started
PAIRS=$(wc -l < "$B/collected_pairs.jsonl" 2>/dev/null | tr -d ' ')
TARGET=$((BASE + PAIRS))

c=$(python3 -c "import json;print(len(json.load(open('$CACHE'))['verdicts']))" 2>/dev/null || echo -1)
done=$((c - BASE)); pct=0; [ "${PAIRS:-0}" -gt 0 ] && pct=$(( done * 100 / PAIRS ))

echo "=== #9 standalone-judger status ==="
if pgrep -f judge_driver >/dev/null; then
  echo "STATE : ⏳ RUNNING (driver alive$(pgrep -f judge_collected_pairs >/dev/null && echo ' + judger active' || echo ', judger between passes'))"
elif [ -f "$B/metrics_gpt_primary.json" ]; then
  echo "STATE : ✅ full n=360 output written"
else
  echo "STATE : ⚠️  driver NOT running (finished, or stopped) — check judge_driver.log; resume with: bash scripts/judge_driver.sh"
fi
echo "PROG  : $done / $PAIRS pairs judged (${pct}%)  ·  cache $c / ~$TARGET"
echo "FRESH : judger.log changed $(python3 -c "import os,time;print(f'{(time.time()-os.path.getmtime(\"$B/judger.log\"))/60:.1f} min ago')" 2>/dev/null)"
echo "--- judger.log (judged / undecided / errors) ---"; tail -2 "$B/judger.log" 2>/dev/null
echo "--- judge_driver.log (restarts) ---"; tail -3 "$B/judge_driver.log" 2>/dev/null
