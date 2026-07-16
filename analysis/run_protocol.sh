#!/usr/bin/env bash
# Full per-protocol empirical pipeline, run SEQUENTIALLY (never two at once — the study
# forbids parallel gas measurement to avoid CPU-contention wall-clock skew; gas values
# themselves are deterministic and re-checked by --gas-repeats).
#
#   STEP 1  gasopt <target> --report report.json --gas-report gas.json  (RQ1/RQ2/RQ3/RQ4)
#   STEP 2  factorial_gas.sh (2x2 cells at runs=200)                     (RQ5)
#
# gasopt leaves the working tree rewritten after STEP 1, which is exactly what the factorial's
# Cells C/D need; Cells A/B come from a worktree at <pre_rewrite_ref> (the pristine baseline).
#
# Usage: run_protocol.sh <protocol> <target_subdir> <pre_rewrite_ref> [-- extra gasopt args]
set -uo pipefail
CS=/home/mfav/gasopt-case-study
GASOPT=/home/mfav/GasOptimizer
P="${1:?protocol}"; TARGET="${2:?target subdir}"; REF="${3:?pre_rewrite_ref}"; shift 3
[ "${1:-}" = "--" ] && shift
OUT="$CS/results/$P"; mkdir -p "$OUT"
cd "$CS"

# Restore pristine before STEP 1 so gasopt's clean-tree gate passes and HEAD==baseline.
git -C "$P" reset --hard "$REF" >/dev/null 2>&1
git -C "$P" clean -fdq -e node_modules >/dev/null 2>&1

{
  echo "===== $P full pipeline  $(date -u) ====="
  echo "gasopt commit  : $(git -C "$GASOPT" rev-parse HEAD)"
  echo "forge          : $(forge --version | head -1)"
  echo "target         : $P/$TARGET"
  echo "pre_rewrite_ref: $REF"
  echo "extra args     : $*"
  echo "=== STEP 1: gasopt --report --gas-report ==="
  # GASOPT_OPT_RUNS: override the project's optimizer_runs for the gas benchmark. Needed for
  # subjects whose default profile sets an infeasible run count (e.g. seaport 4,294,967,295,
  # v4-core 44,444,444) that OOMs the whole-suite compile; gasopt shells out to forge, which
  # reads FOUNDRY_OPTIMIZER_RUNS. When set, gas.json is a runs=<n> measurement (documented),
  # consistent with the runs=200 factorial rather than the infeasible project default.
  if [ -n "${GASOPT_OPT_RUNS:-}" ]; then
    echo "(gas benchmark forced to FOUNDRY_OPTIMIZER_RUNS=$GASOPT_OPT_RUNS — project default is infeasible)"
    export FOUNDRY_OPTIMIZER=true FOUNDRY_OPTIMIZER_RUNS="$GASOPT_OPT_RUNS"
  fi
  node "$GASOPT/dist/index.js" "$P/$TARGET" \
    --report "$OUT/report.json" --gas-report "$OUT/gas.json" \
    --gas-seed 42 --gas-repeats 3 "$@"
  echo "GASOPT-EXIT=$?"
} > "$OUT/run.log" 2>&1

echo "=== STEP 2: RQ5 2x2 factorial (runs=200) ===" | tee -a "$OUT/run.log"
# The factorial extracts per-contract DEPLOYMENT gas only (compile-time; independent of the
# number of fuzz runs), so we lower FOUNDRY_FUZZ_RUNS for speed without changing any RQ5 number.
# Step-1 gas.json (per-function averages) keeps the project's own fuzz config for fidelity.
RQ5_REPEATS="${RQ5_REPEATS:-3}" FOUNDRY_FUZZ_SEED=42 OPT_RUNS=200 \
  FOUNDRY_FUZZ_RUNS="${RQ5_FUZZ_RUNS:-16}" \
  bash "$CS/analysis/factorial_gas.sh" "$CS/$P" "$REF" "$OUT" > "$OUT/rq5.log" 2>&1
echo "FACTORIAL-EXIT=$?" | tee -a "$OUT/run.log"
echo "PIPELINE-DONE $P"
