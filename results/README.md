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
- gasopt commit per protocol: recorded in each `manifest.json` entry (`gasopt_commit`) and each
  `run.log`. Six subjects used `3534bf2` (the multi-version/via-IR build); **Seaport required
  `751da96`**, which fixes the `evm_version` bug that build exposed (see `tool-bugs.md` Bug 6).
- **This run was reproduced on a 31 GiB / 20-core machine (`mfav`), forge 1.7.1** (installed via
  `foundryup -i 1.7.1` to match the earlier `manoel` machine and remove a forge-version confound;
  the box shipped with 1.2.3). node 22, python 3.14 (venv in `analysis/.venv`, pandas 2.3.3,
  matplotlib 3.10.7).
- Protocol sources are checked out pristine into each `<protocol>/` dir; a per-protocol git
  baseline is created by `analysis/setup_baseline.sh` (fresh `git init` of the pristine source,
  deps committed as plain files) so gasopt's `--gas-report` worktree and the RQ5 factorial work
  offline. `pre_rewrite_ref` in each `manifest.json` entry is that baseline commit.
- All gas runs use `--gas-seed 42`; the factorial uses `FOUNDRY_FUZZ_SEED=42`. The factorial
  extracts per-contract DEPLOYMENT gas (compile-time, fuzz-independent), so it runs at a lowered
  `FOUNDRY_FUZZ_RUNS` for speed without affecting any RQ5 number.

## Final measured status (7 in-study subjects)
- **RQ1/RQ2 (rewrite):** all 7 ran end-to-end, 709 rewrites, 14/24 default rules. Seaport only
  after the `751da96` fix.
- **RQ3/RQ4 (gas.json):** aave, core, core-v3, morpho, openzeppelin (library-embedded), v4 — all
  deterministic, **0 `skippedAfterRewriteOnly`**. Seaport not gas-measurable (its suite deploys
  production contracts only via `vm.getCode` from an infeasible via-IR build).
- **RQ5 factorial:** full 2x2 for morpho, openzeppelin, v4; A/C only for aave, core, core-v3
  (their via-IR cells OOM at 31 GiB, or stack-too-deep for Gearbox — a project property, not a
  gasopt regression). v4 project-default gas.json OOMs; measured at runs=200 instead.
- Helper scripts added this run: `analysis/setup_baseline.sh`, `analysis/run_protocol.sh`,
  `analysis/rewrite_then_factorial.sh`, `analysis/mem_watchdog.sh`.

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
