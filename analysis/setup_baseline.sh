#!/usr/bin/env bash
# Reconstitute a per-protocol git baseline for the empirical gas methodology.
#
# WHY: gasopt's --gas-report and the RQ5 factorial both treat the target project's git HEAD
# as the "pre-rewrite" baseline and recover it into a throwaway `git worktree`. The upstream
# protocol sources were re-checked-out fresh (pristine, un-rewritten) into <case-study>/<proto>/
# but WITHOUT their original .git, and the pre_rewrite_refs recorded by the first study machine
# no longer exist. This script gives each protocol a self-contained baseline: a fresh repo whose
# single commit is the pristine upstream source, with lib/ dependencies committed as PLAIN FILES
# (the upstream submodules are already flattened on disk), so the baseline worktree builds
# offline with no network submodule fetch. node_modules / out / cache stay gitignored; the
# harness (GasBenchmark + factorial_gas.sh) symlinks node_modules into the worktree when needed.
#
# This is the documented `--gas-report clean-tree` workflow, not a tool defect: the baseline
# commit IS the original code, so HEAD-as-baseline is exactly the pre-rewrite state.
#
# Usage:  setup_baseline.sh <protocol_dir>
# Output: prints the baseline commit sha (the pre_rewrite_ref) on stdout.
set -euo pipefail
DIR="${1:?protocol dir}"
cd "$DIR"

if [ -e .git ]; then
  echo "[skip] $DIR already a git repo -> $(git rev-parse HEAD)" >&2
  git rev-parse HEAD
  exit 0
fi

# Guard: a nested .git under lib/ would be added as a gitlink and the worktree would not
# populate it. The flattened checkout should have none; refuse if one appears.
if find lib -maxdepth 3 -name .git 2>/dev/null | grep -q .; then
  echo "[error] $DIR/lib contains a nested .git; flatten it before baselining" >&2
  exit 1
fi

git init -q
git add -A
# Some upstream .gitignore files exclude lib/; force it so the baseline is self-contained.
[ -d lib ] && git add -f lib >/dev/null 2>&1 || true
git -c user.email="casestudy@local" -c user.name="gasopt case study" \
    commit -q -m "case-study baseline: pristine upstream source (pre-gasopt)"
git rev-parse HEAD
