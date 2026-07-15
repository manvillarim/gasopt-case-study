#!/usr/bin/env python3
"""
gasopt case-study analysis (Phases 5-6).

Reads every results/<protocol>/*.json produced by the case study and emits, under
analysis/tables/ (CSV, one family per RQ) and analysis/figures/ (PNG):

  RQ1  applicability      : per protocol, did the pipeline run end to end + failure cause
  RQ2  rule coverage      : which of the 25 rules fired, how often, in how many protocols
  RQ3  effectiveness       : deployment gas / bytecode size / mean per-function gas, before/after
  RQ4  correctness         : skippedAfterRewriteOnly counts + declined-rule reasons
  RQ5  factorial (2x2)     : (original x gasopt) x (standard x via-IR) deployment gas

Design rules (from the task spec):
  * No number is invented. A protocol with no measurement is ABSENT from the metric
    tables (and listed as unmeasured), never interpolated.
  * Re-runnable from scratch: `python analysis/run_analysis.py`. All filtering is in code.

Reads are defensive: a missing/empty JSON means "not measured", not an error.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent          # case-study-tool/
RESULTS = ROOT / "results"
TABLES = ROOT / "analysis" / "tables"
FIGS = ROOT / "analysis" / "figures"
TABLES.mkdir(parents=True, exist_ok=True)
FIGS.mkdir(parents=True, exist_ok=True)

# The canonical 25 automated rules, in catalogue order (from `gasopt --list-transforms`).
ALL_RULES = [
    "state-packing", "struct-packing", "avoid-zero-init", "remove-const-loop",
    "factor-loops", "const-folding", "demorgan", "single-line-swap", "delete-storage",
    "cache-storage", "cache-array-member", "cache-array-length", "loop-invariant",
    "pre-increment", "unchecked", "require-error", "short-circuit", "const-folding-state",
    "use-immutable", "use-constant", "avoid-zero-init-state", "visibility",
    "calldata-params", "payable-constructor", "loop-fusion",
]
CLOSED_WORLD_ONLY = {"struct-packing"}  # + the promotion half of `visibility` (gated at runtime)


def load_json(p: Path):
    try:
        txt = p.read_text().strip()
        if not txt:
            return None
        return json.loads(txt)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


MANIFEST = (load_json(RESULTS / "manifest.json") or {}).get("protocols", {})


def is_production(protocol: str, contract_key: str) -> bool:
    """True iff a gas-report contract key '<path>:<Name>' is a production deployable.

    Uses the per-protocol manifest (prod_prefixes / exclude_substrings). Without a
    manifest entry we DON'T guess: return False so unclassified contracts are excluded
    from production gas totals rather than silently inflating them.
    """
    cfg = MANIFEST.get(protocol)
    if not cfg:
        return False
    path = contract_key.split(":", 1)[0]
    if any(sub in path for sub in cfg.get("exclude_substrings", [])):
        return False
    return any(path.startswith(pre) for pre in cfg.get("prod_prefixes", []))


def protocols() -> list[str]:
    if not RESULTS.exists():
        return []
    return sorted(d.name for d in RESULTS.iterdir()
                  if d.is_dir() and (d / "report.json").exists())


# --------------------------------------------------------------------------- RQ1
def rq1_applicability(protos: list[str]) -> pd.DataFrame:
    rows = []
    for p in protos:
        rep = load_json(RESULTS / p / "report.json")
        gas = load_json(RESULTS / p / "gas.json")
        log = (RESULTS / p / "run.log")
        s = (rep or {}).get("summary", {})
        skipped = s.get("filesSkipped", {}) or {}
        rewrite_ok = rep is not None
        gas_ok = gas is not None
        cause = ""
        if not rewrite_ok:
            cause = "rewrite/report step did not complete"
        elif not gas_ok:
            cause = "gas benchmark not produced (see run.log / notes)"
        rows.append({
            "protocol": p,
            "rewrite_ran": rewrite_ok,
            "files_total": s.get("filesTotal"),
            "files_optimised": s.get("filesOptimised"),
            "skipped_imports": skipped.get("imports"),
            "skipped_compile": skipped.get("compileErrors"),
            "skipped_verify": skipped.get("verifyFailed"),
            "gas_measured": gas_ok,
            "end_to_end": rewrite_ok and gas_ok,
            "failure_cause": cause,
        })
    df = pd.DataFrame(rows)
    df.to_csv(TABLES / "rq1_applicability.csv", index=False)
    return df


# --------------------------------------------------------------------------- RQ2
def rq2_rule_coverage(protos: list[str]) -> pd.DataFrame:
    # rule x protocol matrix of applied-rewrite counts.
    data = {}
    for p in protos:
        rep = load_json(RESULTS / p / "report.json")
        applied = ((rep or {}).get("summary", {}) or {}).get("rulesApplied", {}) or {}
        data[p] = applied
    df = pd.DataFrame(index=ALL_RULES)
    for p in protos:
        df[p] = pd.Series(data[p]).reindex(ALL_RULES).fillna(0).astype(int)
    df["total_rewrites"] = df.sum(axis=1)
    df["n_protocols"] = (df[protos] > 0).sum(axis=1)
    df["closed_world_only"] = [r in CLOSED_WORLD_ONLY for r in ALL_RULES]
    df.index.name = "rule"
    df.to_csv(TABLES / "rq2_rule_coverage.csv")

    # stacked bar: rule x count, stacked by protocol (only rules that fired at least once)
    fired = df[df["total_rewrites"] > 0]
    if not fired.empty:
        ax = fired[protos].plot(kind="barh", stacked=True, figsize=(10, max(4, 0.4 * len(fired))))
        ax.set_xlabel("rewrites applied (stacked by protocol)")
        ax.set_ylabel("rule")
        ax.set_title("RQ2: transformation rules fired on production code")
        ax.legend(fontsize=7, ncol=2)
        plt.tight_layout()
        plt.savefig(FIGS / "rq2_rule_coverage.png", dpi=150)
        plt.close()
    return df


# --------------------------------------------------------------------------- RQ3
def rq3_effectiveness(protos: list[str]):
    per_contract = []
    per_proto = []
    for p in protos:
        gas = load_json(RESULTS / p / "gas.json")
        if not gas:
            continue
        table = (gas.get("gasReportTable") or {})
        contracts = [c for c in (table.get("contracts") or [])
                     if is_production(p, c.get("contract", ""))]
        dep_before = dep_after = 0
        size_before = size_after = 0
        n_dep = 0
        fn_mean_deltas = []
        for c in contracts:
            db, da = c.get("deploymentCostBefore"), c.get("deploymentCostAfter")
            sb, sa = c.get("deploymentSizeBefore"), c.get("deploymentSizeAfter")
            if db is not None and da is not None:
                dep_before += db; dep_after += da; n_dep += 1
            if sb is not None and sa is not None:
                size_before += sb; size_after += sa
            for f in (c.get("functions") or []):
                mb, ma = f.get("meanBefore"), f.get("meanAfter")
                if mb is not None and ma is not None and f.get("stable", True):
                    per_contract.append({
                        "protocol": p, "contract": c.get("contract"),
                        "function": f.get("signature"),
                        "mean_before": mb, "mean_after": ma,
                        "mean_delta": ma - mb,
                        "mean_delta_pct": (100.0 * (ma - mb) / mb) if mb else None,
                    })
                    if mb:
                        fn_mean_deltas.append(100.0 * (ma - mb) / mb)
        per_proto.append({
            "protocol": p,
            "contracts_measured": n_dep,
            "deploy_gas_before": dep_before, "deploy_gas_after": dep_after,
            "deploy_gas_delta": dep_after - dep_before,
            "deploy_gas_delta_pct": (100.0 * (dep_after - dep_before) / dep_before) if dep_before else None,
            "deploy_size_before": size_before, "deploy_size_after": size_after,
            "deploy_size_delta": size_after - size_before,
            "deploy_size_delta_pct": (100.0 * (size_after - size_before) / size_before) if size_before else None,
            "mean_fn_gas_delta_pct_median": (pd.Series(fn_mean_deltas).median() if fn_mean_deltas else None),
            "n_functions_measured": len(fn_mean_deltas),
            "deterministic": gas.get("deterministic"),
        })
    dfc = pd.DataFrame(per_contract)
    dfp = pd.DataFrame(per_proto)
    dfc.to_csv(TABLES / "rq3_effectiveness_per_function.csv", index=False)
    dfp.to_csv(TABLES / "rq3_effectiveness_per_protocol.csv", index=False)

    if not dfp.empty:
        fig, ax = plt.subplots(figsize=(9, max(3, 0.5 * len(dfp))))
        ax.barh(dfp["protocol"], dfp["deploy_gas_delta_pct"])
        ax.axvline(0, color="k", lw=0.8)
        ax.set_xlabel("deployment gas change (%) after gasopt (negative = cheaper)")
        ax.set_title("RQ3: deployment-gas effect per protocol (project-default compiler)")
        plt.tight_layout()
        plt.savefig(FIGS / "rq3_deploy_gas.png", dpi=150)
        plt.close()
    return dfp


# --------------------------------------------------------------------------- RQ4
def rq4_correctness(protos: list[str]) -> pd.DataFrame:
    rows = []
    for p in protos:
        gas = load_json(RESULTS / p / "gas.json")
        rep = load_json(RESULTS / p / "report.json")
        declined = []
        for f in (rep or {}).get("files", []):
            for d in f.get("rulesDeclined", []) or []:
                declined.append(d)
        skipped_after = (gas or {}).get("skippedAfterRewriteOnly", []) if gas else None
        rows.append({
            "protocol": p,
            "gas_measured": gas is not None,
            "skipped_after_rewrite_only": (len(skipped_after) if skipped_after is not None else None),
            "skipped_after_rewrite_tests": ("; ".join(skipped_after) if skipped_after else ""),
            "skipped_pre_existing": (len((gas or {}).get("skippedPreExisting", []) or []) if gas else None),
            "declined_rewrites": len(declined),
            "nondeterministic_tests": (len((gas or {}).get("nonDeterministicTests", []) or []) if gas else None),
        })
    df = pd.DataFrame(rows)
    df.to_csv(TABLES / "rq4_correctness.csv", index=False)
    return df


# --------------------------------------------------------------------------- RQ5
CELLS = {
    "A": ("cell-A-orig-standard", "original", "standard"),
    "B": ("cell-B-orig-viair",    "original", "via-IR"),
    "C": ("cell-C-gasopt-standard", "gasopt", "standard"),
    "D": ("cell-D-gasopt-viair",    "gasopt", "via-IR"),
}


def _parse_cell_runs(protocol: str, rq5_dir: Path, prefix: str) -> dict[str, float] | None:
    """Return {contract: median production deployment gas across repeats}, or None if unmeasured."""
    runs = sorted(rq5_dir.glob(f"{prefix}.run*.json"))
    per_contract: dict[str, list[float]] = {}
    any_ok = False
    for r in runs:
        arr = load_json(r)
        if not isinstance(arr, list):
            continue
        any_ok = True
        for e in arr:
            if isinstance(e, dict) and isinstance(e.get("contract"), str):
                if not is_production(protocol, e["contract"]):
                    continue
                dep = (e.get("deployment") or {}).get("gas")
                if dep is not None:
                    per_contract.setdefault(e["contract"], []).append(float(dep))
    if not any_ok or not per_contract:
        return None
    return {c: float(pd.Series(v).median()) for c, v in per_contract.items()}


def rq5_factorial(protos: list[str]) -> pd.DataFrame:
    rows = []
    for p in protos:
        rq5_dir = RESULTS / p / "rq5"
        if not rq5_dir.exists():
            continue
        cell_maps = {k: _parse_cell_runs(p, rq5_dir, CELLS[k][0]) for k in CELLS}
        # sum deployment gas over contracts present in ALL measured cells (fair comparison)
        measured = {k: v for k, v in cell_maps.items() if v}
        if not measured:
            continue
        common = set.intersection(*[set(v.keys()) for v in measured.values()])
        totals = {k: (sum(cell_maps[k][c] for c in common) if cell_maps[k] else None)
                  for k in CELLS}
        A, B, C, D = totals["A"], totals["B"], totals["C"], totals["D"]

        def pct(frm, to):
            return (100.0 * (to - frm) / frm) if (frm and to is not None) else None
        rows.append({
            "protocol": p,
            "contracts_compared": len(common),
            "A_orig_standard": A, "B_orig_viair": B,
            "C_gasopt_standard": C, "D_gasopt_viair": D,
            "compiler_alone_pct_A_to_B": pct(A, B),      # via-IR alone
            "gasopt_alone_pct_A_to_C": pct(A, C),        # gasopt alone, common config
            "gasopt_under_viair_pct_B_to_D": pct(B, D),  # does gasopt hold under via-IR?
            "best_vs_baseline_pct_A_to_D": pct(A, D),    # best practical config
        })
    df = pd.DataFrame(rows)
    df.to_csv(TABLES / "rq5_factorial.csv", index=False)

    if not df.empty:
        sub = df.set_index("protocol")[["A_orig_standard", "B_orig_viair",
                                        "C_gasopt_standard", "D_gasopt_viair"]]
        ax = sub.plot(kind="bar", figsize=(10, 5))
        ax.set_ylabel("summed deployment gas over compared contracts")
        ax.set_title("RQ5: 2x2 factorial deployment gas (lower = cheaper)")
        ax.legend(["A orig+std", "B orig+viaIR", "C gasopt+std", "D gasopt+viaIR"], fontsize=8)
        plt.tight_layout()
        plt.savefig(FIGS / "rq5_factorial.png", dpi=150)
        plt.close()
    return df


def main():
    protos = protocols()
    print(f"protocols with a report.json: {protos}")
    rq1 = rq1_applicability(protos)
    rq2 = rq2_rule_coverage(protos)
    rq3 = rq3_effectiveness(protos)
    rq4 = rq4_correctness(protos)
    rq5 = rq5_factorial(protos)
    print("\n=== RQ1 applicability ===")
    print(rq1.to_string(index=False) if not rq1.empty else "(none)")
    print("\n=== RQ2 rules that fired ===")
    fired = rq2[rq2["total_rewrites"] > 0][["total_rewrites", "n_protocols"]]
    print(fired.to_string() if not fired.empty else "(none fired)")
    print("\n=== RQ3 per-protocol effectiveness ===")
    print(rq3.to_string(index=False) if not rq3.empty else "(no gas measured yet)")
    print("\n=== RQ4 correctness ===")
    print(rq4.to_string(index=False) if not rq4.empty else "(none)")
    print("\n=== RQ5 factorial ===")
    print(rq5.to_string(index=False) if not rq5.empty else "(no factorial measured yet)")
    print(f"\nTables -> {TABLES}\nFigures -> {FIGS}")


if __name__ == "__main__":
    main()
