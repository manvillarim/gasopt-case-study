# gasopt tool fixes found during the case study (engineering log)

**Scope note:** This file is an internal engineering/provenance log. Per the user's
instruction, these tool fixes are NOT written up in the article — only the final optimisation
results are reported there. Kept here so we know which gasopt version produced which JSONs and
which protocols must be reprocessed.

## Tool version
- Baseline (morpho-blue, v4-core runs): gasopt commit `02bd38ae...` (pre-fix).
- Fixed version: working tree of `/home/manoel/gasopt` after the fixes below (rebuild `npm run
  build`). Commit hash to be recorded once committed.

## What exposed them
Running gasopt on **Lido (`core/`)**, a production repo that (a) is not self-contained until
`yarn install` vendors its deps, and (b) spans four incompatible compiler series
(0.4.24 / 0.6.11 / 0.6.12 / 0.8.9 / 0.8.25) with per-path via-IR compilation restrictions.
Before the fixes: 33/128 files optimised, 24 skipped (14 compile-error, 10 verify-failed).

## Fixes (all in gasopt source, general — not Lido-specific)

1. **Range-pragma compiler resolution** (`src/index.ts`, `src/NativeSolc.ts`).
   Old code pinned an EXACT pragma but fell back to the *latest* compiler for any RANGE
   pragma, ignoring the range's UPPER bound — so `^0.4.24` (i.e. `<0.5.0`) was compiled with
   0.8.29 and failed to parse. Fix: for a range pragma, pick the highest compiler that
   `semver.maxSatisfying` accepts among the versions Foundry already installed via svm (the
   ones it actually built the project with). New `enumerateInstalledSolc()`.

2. **Language-feature gating by compiler version** (`src/index.ts`).
   `require-error` rewrites to a custom `error X();` (a >=0.8.4 feature) and `unchecked {}`
   blocks (>=0.8.0). They were firing on 0.4.x/0.6.x files, emitting syntax those compilers
   cannot parse. The verify gate caught it (original kept) but forfeited every other safe
   rewrite on the file. Fix: gate both on the resolved `solcVersion` via `semver.gte`.

3. **Serialise for the file's own compiler version** (`src/index.ts`).
   The `ASTWriter` was always constructed with `LatestCompilerVersion`, emitting modern
   syntax into old files: a 0.4.24 fallback printed as `fallback() external` (invalid pre-0.6;
   needs unnamed `function ()`) and a 0.6.x constructor printed with no visibility (0.6.x
   requires `constructor() public`). Fix: build both writers with the resolved version.

4. **AST-only parse** (`src/index.ts`).
   The parse step requested `CompilationOutput.ALL` (incl. bytecode), so contracts a project
   only builds with via-IR raised "Stack too deep" / "UnimplementedFeatureError" during a
   phase we don't even need (we only need the AST to rewrite). Fix: request
   `[CompilationOutput.AST]` for the parse.

5. **via-IR retry + pre-existing-error baseline in the verify gate** (`src/CompileVerify.ts`).
   (a) If the rewritten source fails codegen with "Stack too deep"/"UnimplementedFeatureError",
   retry once with `{ viaIR: true, optimizer }` — the way the project actually compiles those
   paths — instead of rejecting a valid rewrite over a legacy-pipeline limit.
   (b) gasopt compiles one file in isolation, which can surface artifacts the whole-project
   `forge` build never sees (a contract reached through two import paths → "Identifier already
   declared"). On a candidate failure, recompile the UNTOUCHED original the same way; if it
   fails with the SAME normalised diagnostic, the failure is not the rewrite's doing → accept.

## Result on Lido after fixes
24 skips → a small residual (see `results/core/run.log`), all safely handled by the verify
gate (original kept) or skipped at parse (nothing written) — no unsafe output. Remaining
residual skips are acceptable per the user ("if the tool reverted it, it's fine").

## Reprocessing impact on already-run protocols
- **morpho-blue, v4-core** are pure 0.8.x, self-contained, and did not hit stack-too-deep at
  parse. Fixes 1–2 (version-gating) don't apply to >=0.8.4 code; fix 3 (writer version)
  produces identical modern-syntax output for 0.8.x; fixes 4–5 only change the failure path.
  => rewrites unchanged; **RQ5 gas (from forge) is independent of these fixes.** A confirmation
  re-run of their `report.json` rule counts is planned (cheap, dry-run) before finalising.

---

# Bug found on the mfav machine (31GiB), forge 1.7.1, gasopt 3534bf2 -> 751da96

## Bug 6 — `evm_version` dropped into PathOptions instead of solc compilerSettings
- **Exposed by:** Seaport (`seaport/`, solc **0.8.24**, `evm_version='cancun'`).
- **Category:** infrastructure / compiler-plumbing (an APPLICABILITY bug, not a
  behaviour-preservation bug — it made gasopt SKIP too much, never emit unsafe output).
- **Symptom:** every Seaport file that transitively imports `seaport-core`'s
  `ReentrancyGuard.sol` (which uses EIP-1153 `tload`/`tstore`) was skipped with
  `DeclarationError: Function "tload" not found` — dozens of `helpers/navigator/**` files.
- **Root cause:** gasopt *did* read `evm_version` from `foundry.toml` (`readFoundryConfig`)
  and intended to pass it to the compiler, but it assigned it to solc-typed-ast's
  `PathOptions` object (`pathOptions.evmVersion = ...`). `PathOptions` has only
  `{remapping, basePath, includePath}`, so the field was silently ignored and every compile
  ran at solc's DEFAULT evm target. For solc **< 0.8.25** that default is *shanghai*, where
  `tload`/`tstore` do not exist — hence the parse error. (solc >= 0.8.25 defaults to cancun,
  which is why aave 0.8.27, v4 0.8.26, OZ 0.8.31, gearbox 0.8.23-without-tload, and Lido were
  all unaffected: **blast radius = Seaport only** among the seven subjects.)
- **Fix (gasopt commit `751da96`):** pass `evm_version` through solc's `compilerSettings`
  argument (the 5th arg of `compileSol`, 6th of `compileSourceString`) in every compile site:
  the AST parse (`optimizeFileOnDisk`, `optimizeSource`), the verify gate (`CompileVerify`,
  merged into BOTH the base compile and the via-IR retry), and the test-suite fixer
  (`TestSuiteFixer`). No precondition was touched — this is pure compiler plumbing, faithful
  to the code's already-stated intent ("pass evm_version so cancun/shanghai opcodes are
  recognised"); only the wiring was wrong.
- **Regression fixture:** `test/fixtures/payable-constructor/positive/cancun-transient-storage.{sol,json}`
  — a `tload`/`tstore` contract pinned to solc `0.8.24` + `evm_version:'cancun'`; it only
  parses (and the rewrite only fires) with the fix. Fixture harness extended so a fixture can
  pin `solcVersion`/`evmVersion` (`applyOne`, `tryCompile`, `FixtureMeta`). All 25 transforms'
  fixtures still pass (payable-constructor 3/3 -> 4/4).
- **Reprocessing impact:** Seaport had NOT been fully measured before the fix (its first run
  was aborted the moment the skips appeared), so no prior Seaport number needs discarding. All
  other subjects were measured with solc >= 0.8.25 (cancun default) or without tload, so their
  numbers are unaffected. Seaport is (re-)run end-to-end on `751da96`; its `manifest.json`
  `gasopt_commit` records `751da96`, distinct from the `3534bf2` used by the others.

## Non-bug (recorded for provenance) — Gearbox does not compile under via-IR
- **Observed:** in the RQ5 factorial, Gearbox (`core-v3`) cells B (original+via-IR) and D
  (gasopt+via-IR) both fail to compile at `optimizer_runs=200` with the **byte-identical** Yul
  error `Variable expr_component is 1 too deep in the stack [...]`.
- **Diagnosis:** the failure is present in the ORIGINAL code (cell B) exactly as in the gasopt
  code (cell D), so it is a property of Gearbox under via-IR, **not** a gasopt regression.
  Gearbox's own default profile uses the standard optimiser at `runs=1000` (no via-IR); via-IR
  is simply inapplicable to it. Its RQ5 via-IR column is therefore N/A and A->C (gasopt alone,
  standard) is the comparison. No gasopt change warranted.
