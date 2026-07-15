#!/usr/bin/env bash
# RQ5 2x2 factorial gas harness (Phase 4 of the case study).
#
# Measures the four cells of (code: original x gasopt) x (compiler: standard x via-IR)
# with ONE fixed fuzz seed and the same repeat count in every cell, so the cells are
# directly comparable.
#
#   Cell A: original code   + standard optimizer (runs=200, via_ir off)   -> baseline
#   Cell B: original code   + via-IR             (runs=200, via_ir on)
#   Cell C: gasopt code     + standard optimizer
#   Cell D: gasopt code     + via-IR
#
# "original code" = a git worktree checked out at <pre_rewrite_ref> (the commit that was
# HEAD when gasopt ran, i.e. before gasopt rewrote the working tree).
# "gasopt code"   = the current working tree of <project_dir> (Phase 3 left it rewritten;
#                   the study intentionally does NOT revert it until D is measured).
#
# Each cell is captured as raw `forge test --gas-report --json` output (a JSON array,
# one entry per contract). The Python analysis aggregates across repeats and cells.
#
# Usage:
#   factorial_gas.sh <project_dir> <pre_rewrite_ref> <out_dir> [match_regex]
# Env:
#   RQ5_REPEATS      repeats per cell (default 3). Reduce for very large protocols; the
#                    analysis records the count so any reduction is explicit, not silent.
#   FOUNDRY_FUZZ_SEED  fixed seed for every cell (default 42).
#   OPT_RUNS         optimizer_runs held constant across standard/via-IR (default 200) so
#                    via_ir is the only factor that changes between the two compiler cells.
set -uo pipefail

PROJECT_DIR="${1:?project_dir}"
PRE_REWRITE_REF="${2:?pre_rewrite_ref}"
OUT_DIR="${3:?out_dir}"
MATCH_REGEX="${4:-}"

RQ5_REPEATS="${RQ5_REPEATS:-3}"
SEED="${FOUNDRY_FUZZ_SEED:-42}"
OPT_RUNS="${OPT_RUNS:-200}"
FORGE="${FORGE:-forge}"

mkdir -p "$OUT_DIR/rq5"
META="$OUT_DIR/rq5/meta.json"
{
  echo "{"
  echo "  \"project_dir\": \"$PROJECT_DIR\","
  echo "  \"pre_rewrite_ref\": \"$PRE_REWRITE_REF\","
  echo "  \"repeats\": $RQ5_REPEATS,"
  echo "  \"seed\": \"$SEED\","
  echo "  \"optimizer_runs\": $OPT_RUNS,"
  echo "  \"match_regex\": \"$MATCH_REGEX\","
  echo "  \"generated_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
  echo "}"
} > "$META"

matchargs=()
[ -n "$MATCH_REGEX" ] && matchargs=(--match-test "$MATCH_REGEX")

# Run one cell N times into $OUT_DIR/rq5/<label>.run<k>.json
run_cell() {
  local dir="$1" label="$2" via_ir="$3"
  echo "=== cell $label  (dir=$dir via_ir=$via_ir) ==="
  local k
  for k in $(seq 1 "$RQ5_REPEATS"); do
    local out="$OUT_DIR/rq5/${label}.run${k}.json"
    local log="$OUT_DIR/rq5/${label}.run${k}.log"
    FOUNDRY_FUZZ_SEED="$SEED" \
    FOUNDRY_OPTIMIZER=true \
    FOUNDRY_OPTIMIZER_RUNS="$OPT_RUNS" \
    FOUNDRY_VIA_IR="$via_ir" \
      "$FORGE" test --gas-report --json "${matchargs[@]}" --root "$dir" \
      > "$out" 2> "$log"
    local rc=$?
    echo "  run$k rc=$rc bytes=$(wc -c < "$out" 2>/dev/null || echo 0)  ($label)"
    # If forge produced no parseable JSON, keep the (empty) file + log for the analysis
    # to record the cell as unmeasured rather than fabricating a number.
  done
}

# --- Cells C and D: gasopt (current working tree) ---
run_cell "$PROJECT_DIR" "cell-C-gasopt-standard" "false"
run_cell "$PROJECT_DIR" "cell-D-gasopt-viair"   "true"

# --- Cells A and B: original code via a throwaway worktree at pre_rewrite_ref ---
REPO_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)"
WT="$(mktemp -d /tmp/gasopt-rq5-orig-XXXXXX)"
rm -rf "$WT"  # git worktree add wants a non-existent path
echo "=== preparing original-code worktree at $PRE_REWRITE_REF -> $WT ==="
if git -C "$REPO_ROOT" worktree add --detach "$WT" "$PRE_REWRITE_REF" > "$OUT_DIR/rq5/worktree.log" 2>&1; then
  git -C "$WT" submodule update --init --recursive >> "$OUT_DIR/rq5/worktree.log" 2>&1
  # Reuse the main checkout's node_modules if present (some projects need it to build).
  if [ -d "$REPO_ROOT/node_modules" ] && [ ! -e "$WT/node_modules" ]; then
    ln -s "$REPO_ROOT/node_modules" "$WT/node_modules"
  fi
  # The original worktree also needs the same remappings.txt the prep commit added; the
  # prep commit IS pre_rewrite_ref, so the checked-out tree already contains it.
  run_cell "$WT" "cell-A-orig-standard" "false"
  run_cell "$WT" "cell-B-orig-viair"   "true"
  git -C "$REPO_ROOT" worktree remove --force "$WT" >> "$OUT_DIR/rq5/worktree.log" 2>&1
  git -C "$REPO_ROOT" worktree prune >> "$OUT_DIR/rq5/worktree.log" 2>&1
else
  echo "[ERROR] could not create original-code worktree; cells A/B unmeasured" | tee -a "$OUT_DIR/rq5/worktree.log"
fi

echo "=== factorial done for $OUT_DIR ==="
