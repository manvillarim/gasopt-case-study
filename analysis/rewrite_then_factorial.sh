#!/usr/bin/env bash
# For a protocol whose gas.json (RQ3/RQ4) is ALREADY valid and need not be re-measured, but
# whose RQ5 factorial is missing/incomplete (e.g. aave: cells B/D via-IR failed by OOM on the
# old 16GiB box): re-apply gasopt to put the rewritten source on disk (STEP 1, --report only,
# NO gas benchmark), then run the 2x2 factorial (STEP 2). gasopt is deterministic at a fixed
# commit, so the rewritten tree reproduces the one that produced the existing gas.json.
#
# Usage: rewrite_then_factorial.sh <protocol> <target_subdir> <pre_rewrite_ref> [-- extra gasopt args]
set -uo pipefail
CS=/home/mfav/gasopt-case-study
GASOPT=/home/mfav/GasOptimizer
P="${1:?protocol}"; TARGET="${2:?target}"; REF="${3:?ref}"; shift 3
[ "${1:-}" = "--" ] && shift
OUT="$CS/results/$P"; mkdir -p "$OUT"
cd "$CS"

git -C "$P" reset --hard "$REF" >/dev/null 2>&1
git -C "$P" clean -fdq -e node_modules >/dev/null 2>&1

{
  echo "===== $P rewrite+factorial  $(date -u) ====="
  echo "gasopt commit  : $(git -C "$GASOPT" rev-parse HEAD)"
  echo "pre_rewrite_ref: $REF"
  echo "note           : gas.json already valid; re-applying rewrite ONLY to enable the factorial"
  echo "=== STEP 1: gasopt --report (rewrite tree; no gas benchmark) ==="
  node "$GASOPT/dist/index.js" "$P/$TARGET" --report "$OUT/report.json" "$@"
  echo "GASOPT-EXIT=$?"
} > "$OUT/rewrite.log" 2>&1

echo "=== STEP 2: RQ5 2x2 factorial (runs=200) ==="
RQ5_REPEATS="${RQ5_REPEATS:-3}" FOUNDRY_FUZZ_SEED=42 OPT_RUNS=200 \
  FOUNDRY_FUZZ_RUNS="${RQ5_FUZZ_RUNS:-16}" \
  bash "$CS/analysis/factorial_gas.sh" "$CS/$P" "$REF" "$OUT" > "$OUT/rq5.log" 2>&1
echo "FACTORIAL-EXIT=$? ; PIPELINE-DONE $P"
