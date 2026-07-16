#!/usr/bin/env bash
# Memory watchdog for the via-IR RQ5 cells of large protocols (e.g. Aave). A whole-suite
# via-IR compile of a big codebase can exhaust RAM; without a guard an OOM can hang or crash
# the host. This kills solc when MemAvailable drops below a threshold, turning a would-be
# machine-OOM into a clean per-cell compile failure (0-byte gas JSON -> the factorial's
# skip-on-failure records the cell as unmeasured, never a fabricated number).
#
# Usage: mem_watchdog.sh [threshold_kb] [logfile] [sentinel]
#   Stops when the sentinel file appears (touch it to end the watchdog).
set -u
THRESHOLD_KB="${1:-1258291}"                    # ~1.2 GiB
LOG="${2:-/tmp/gasopt-mem-watchdog.log}"
SENTINEL="${3:-/tmp/gasopt-mem-watchdog.stop}"
rm -f "$SENTINEL"
echo "watchdog start $(date -u +%H:%M:%S) threshold=${THRESHOLD_KB}KB" >> "$LOG"
while [ ! -f "$SENTINEL" ]; do
  avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  if [ -n "$avail" ] && [ "$avail" -lt "$THRESHOLD_KB" ]; then
    echo "$(date -u +%H:%M:%S) MemAvailable=${avail}KB < ${THRESHOLD_KB}KB -> killing solc" >> "$LOG"
    pkill -9 -f "svm/.*/solc" 2>/dev/null
    pkill -9 -x solc 2>/dev/null
  fi
  sleep 2
done
echo "watchdog stop $(date -u +%H:%M:%S)" >> "$LOG"
