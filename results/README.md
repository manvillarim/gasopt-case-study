# Case-study results — methodology & provenance

Every number in the article is computed by `analysis/run_analysis.py` from the JSON files
under `results/<protocol>/`. Nothing is hand-entered. A protocol with no measurement is
**absent** from the metric tables (never interpolated).

## Files per protocol (`results/<protocol>/`)
- `dry-run.json` — `gasopt --dry-run --report` (parsing/matching validation, RQ1).
- `report.json` — `gasopt --report` (rules applied/declined per file/contract; RQ1, RQ2, RQ4-declines).
- `gas.json`    — `gasopt --gas-report` (Foundry before/after under the project-default compiler;
  RQ3 deployment gas/size + per-function gas, RQ4 `skippedAfterRewriteOnly`).
- `run.log`     — full stdout/stderr of the gasopt run; first lines record the **gasopt commit**
  and the protocol's **pre-rewrite baseline HEAD** (per Phase 0 item 5).
- `rq5/cell-{A,B,C,D}.run{k}.json` — raw `forge test --gas-report --json` for the 2×2 factorial
  (Phase 4). `rq5/meta.json` records seed/repeats/optimizer_runs.
- `rq5.log`     — factorial harness log.

## Tool + reproducibility
- gasopt commit for all runs: recorded in `results/TOOL-COMMIT.txt` and each `run.log`.
- forge 1.7.1, node 22, python 3.14 (pandas 2.3.3, matplotlib 3.10.7).
- All gas runs use `--gas-seed 42` and, for the factorial, `FOUNDRY_FUZZ_SEED=42`.

## Standing methodology decisions
1. **Target = production dir only** (`src/` or `contracts/`), never the whole repo. Test/mock/
   script paths are excluded with `--exclude`. `results/manifest.json` records, per protocol,
   the production path prefixes and exclude substrings used to filter gas-report contracts down
   to real deployables (e.g. a rewritten library inlined into a *test* harness must not be
   counted as production savings).
2. **Remappings.** Auto-discovery first. Projects that rely on Foundry's implicit `lib/`
   remapping (no committed `remappings.txt`, e.g. morpho-blue) get one generated with
   `forge remappings > remappings.txt`, which is then **committed** so the `--gas-report`
   clean-tree gate is satisfied and that commit serves as the pre-rewrite baseline. This is the
   documented `--remappings` workflow, not a tool defect. Projects that already ship
   `remappings.txt` (e.g. v4-core) need no prep commit.
3. **Working tree is NOT reverted after the gasopt run** until the RQ5 factorial has measured
   Cell D (gasopt code under via-IR), which requires the rewritten source still on disk.
4. **RQ5 factorial (2×2).** `analysis/factorial_gas.sh` measures (code: original × gasopt) ×
   (compiler: standard × via-IR) with `optimizer_runs` held constant (200) so **via-IR is the
   only factor** that changes between the two compiler columns. Original code = git worktree at
   the pre-rewrite ref; gasopt code = current working tree.
5. **No mainnet RPC available.** Fork-dependent suites (aave-v3-origin, comet, and especially
   fluid — 47 fork sites) cannot execute their fork tests; their gas is recorded as
   **"not measured — requires RPC"**, never estimated. The rewrite/report step (RQ1/RQ2) still
   runs for them.
6. **Hardhat-only subjects** with no runnable `forge` suite (account-abstraction has no
   `foundry.toml`; comet has 0 `*.t.sol`) yield RQ1/RQ2 data only; RQ3/RQ5 recorded as not
   gas-measured, with the reason.

## Tool bugs
Real gasopt defects found during the study are logged in `results/tool-bugs.md` (with the
protocol that exposed them, root cause, fix, regression fixture, and which protocols were
re-run). Harness/methodology issues in *this* study's own scripts are fixed here and noted in
this file, kept separate from gasopt defects.
