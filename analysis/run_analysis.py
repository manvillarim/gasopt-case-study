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
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# Article-figure style (validated palette; see gasopt_article.tex figures).
ART_BLUE = "#2a78d6"
ART_GREEN = "#008300"
ART_MAGENTA = "#e87ba4"
ART_RED = "#d03b3b"
ART_INK = "#0b0b0b"
ART_INK2 = "#52514e"
ART_GRID = "#e4e3df"
ART_NEUTRAL = "#c9c8c3"
ART_SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
           "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
ART_RC = {"font.size": 9, "font.family": "DejaVu Sans", "text.color": ART_INK,
          "axes.edgecolor": ART_GRID, "axes.labelcolor": ART_INK,
          "xtick.color": ART_INK2, "ytick.color": ART_INK2,
          "figure.facecolor": "white", "axes.facecolor": "white"}
NICE_NAME = {"aave-v3-origin": "Aave V3", "core": "Lido", "core-v3": "Gearbox V3",
             "morpho-blue": "Morpho Blue", "openzeppelin-contracts": "OpenZeppelin",
             "seaport": "Seaport", "v4-core": "Uniswap V4"}

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


def is_library_embedded(protocol: str) -> bool:
    """True for a pure-library subject (e.g. OpenZeppelin) whose contracts are never
    deployed standalone: they are inherited/imported, so a Foundry gas report attributes
    their deploy cost and runtime gas to the test/mock CONTRACTS that embed them. For such a
    subject the strict production filter yields nothing, so we measure gasopt's effect through
    the embedding harnesses instead, labelled 'library-embedded' so it is never conflated with
    a standalone production-deployment saving. Gated on an explicit manifest flag."""
    return bool(MANIFEST.get(protocol, {}).get("library_embedded", False))


def gas_scope_contracts(protocol: str, contracts: list) -> tuple[list, str]:
    """Return (contracts_to_count, scope_label). Strict production deployables when any exist;
    otherwise, for a library_embedded subject, every gas-reported contract (the embedding
    harnesses) with the 'library-embedded' label; otherwise an empty list ('none')."""
    prod = [c for c in contracts if is_production(protocol, c.get("contract", ""))]
    if prod:
        return prod, "production"
    if is_library_embedded(protocol):
        return list(contracts), "library-embedded"
    return [], "none"


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

    # rule x protocol matrix (the article's fig:rq2): count-annotated cells on a
    # sequential ramp, protocols ordered by total rewrites, per-rule totals in the margin.
    fired = df[df["total_rewrites"] > 0].sort_values("total_rewrites", ascending=False)
    if not fired.empty:
        proto_order = sorted(protos, key=lambda p: -int(df[p].sum()))
        maxc = int(fired[proto_order].to_numpy().max())
        with plt.rc_context(ART_RC):
            fig, ax = plt.subplots(figsize=(6.8, 0.31 * len(fired) + 1.2))
            nr, npr = len(fired), len(proto_order)
            for i, (rule, row) in enumerate(fired.iterrows()):
                for j, p in enumerate(proto_order):
                    c = int(row[p])
                    if not c:
                        continue
                    t = math.sqrt(c) / math.sqrt(maxc)
                    col = ART_SEQ[min(int(t * (len(ART_SEQ) - 1) + 0.5), len(ART_SEQ) - 1)]
                    ax.add_patch(Rectangle((j + 0.06, nr - 1 - i + 0.06), 0.88, 0.88,
                                           facecolor=col, edgecolor="none"))
                    ax.text(j + 0.5, nr - 1 - i + 0.5, str(c), ha="center", va="center",
                            color="white" if t > 0.55 else ART_INK, fontsize=8.5)
                ax.text(npr + 0.25, nr - 1 - i + 0.5, str(int(row["total_rewrites"])),
                        ha="right", va="center", color=ART_INK, fontsize=8.5, fontweight="bold")
                ax.text(npr + 0.45, nr - 1 - i + 0.5, f"({int(row['n_protocols'])})",
                        ha="left", va="center", color=ART_INK2, fontsize=8)
            ax.set_xlim(0, npr + 1.1); ax.set_ylim(0, nr)
            ax.set_xticks([j + 0.5 for j in range(npr)])
            ax.set_xticklabels([NICE_NAME.get(p, p) for p in proto_order],
                               rotation=30, ha="right", fontsize=8.5)
            ax.set_yticks([nr - 1 - i + 0.5 for i in range(nr)])
            ax.set_yticklabels(list(fired.index), fontsize=8.5, fontfamily="DejaVu Sans Mono")
            ax.text(npr + 0.25, nr + 0.25, "total", ha="right", va="bottom", fontsize=8, color=ART_INK2)
            ax.text(npr + 0.45, nr + 0.25, "(subjects)", ha="left", va="bottom", fontsize=8, color=ART_INK2)
            for s in ax.spines.values():
                s.set_visible(False)
            ax.tick_params(length=0)
            plt.tight_layout()
            plt.savefig(FIGS / "rq2_rule_matrix.png", dpi=220)
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
        contracts, scope = gas_scope_contracts(p, table.get("contracts") or [])
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
                        "calls_after": f.get("callsAfter"),
                    })
                    if mb:
                        fn_mean_deltas.append(100.0 * (ma - mb) / mb)
        per_proto.append({
            "protocol": p,
            "scope": scope,
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

    # per-function runtime scatter (the article's fig:rq3): mean per-call delta (%)
    # vs. how often the suite calls the function; stable production entries only.
    pts = dfc.dropna(subset=["mean_delta_pct", "calls_after"])
    pts = pts[pts["calls_after"] > 0]
    if not pts.empty:
        # curated labels for the named outliers discussed in the article's RQ3 text
        annot = {
            ("PoolInstance", "flashLoan(address,address[],uint256[],uint256[],address,bytes,uint16)"):
                ("Aave flashLoan  +3.0%", (0, 9), "center"),
            ("AaveV3ConfigEngine",
             "listAssetsCustom((string,string),((address,string,address,(uint256,uint256,uint256,uint256),"
             "uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256),(address,address))[])"):
                ("Aave listAssetsCustom  −1.9%", (8, -3), "left"),
            ("RewardsController", "claimRewards(address[],uint256,address,address)"):
                ("Aave claimRewards  +0.46%", (8, 4), "left"),
            ("Morpho", "liquidate((address,address,address,address,uint256),address,uint256,uint256,bytes)"):
                ("Morpho liquidate  −0.07%", (-10, -4), "right"),
            ("ERC20Mock", "approve(address,uint256)"):
                ("OZ ERC20Mock.approve  +0.03%", (-4, 9), "right"),
            ("ATokenInstance", "burn(address,address,uint256,uint256,uint256)"):
                ("Aave aToken.burn  −0.23%", (10, -13), "left"),
        }
        with plt.rc_context(ART_RC):
            fig, ax = plt.subplots(figsize=(6.8, 3.9))
            ax.axhline(0, color=ART_GRID, lw=1, zorder=1)
            zero = pts[pts["mean_delta_pct"] == 0]
            sav = pts[pts["mean_delta_pct"] < 0]
            reg = pts[pts["mean_delta_pct"] > 0]
            ax.scatter(zero["calls_after"], [0] * len(zero), s=12, color=ART_NEUTRAL,
                       alpha=.55, linewidths=0, zorder=2)
            ax.scatter(sav["calls_after"], sav["mean_delta_pct"], s=26, color=ART_BLUE,
                       linewidths=0, zorder=3, label="cheaper after gasopt")
            ax.scatter(reg["calls_after"], reg["mean_delta_pct"], s=26, color=ART_RED,
                       linewidths=0, zorder=3, label="more expensive")
            for _, r in pts[pts["mean_delta_pct"] != 0].iterrows():
                key = (str(r["contract"]).split(":")[-1], r["function"])
                if key in annot:
                    lab, off, ha = annot[key]
                    ax.annotate(lab, (r["calls_after"], r["mean_delta_pct"]),
                                textcoords="offset points", xytext=off, fontsize=7.5,
                                color=ART_INK, ha=ha)
            ax.set_xscale("log")
            ax.set_xlabel("calls made to the function across the suite (log)")
            ax.set_ylabel("mean per-call gas change (%)")
            ax.set_ylim(-2.4, 3.4)
            ax.legend(frameon=False, fontsize=8, loc="upper left")
            for s in ["top", "right"]:
                ax.spines[s].set_visible(False)
            ax.grid(axis="y", color=ART_GRID, lw=.6, alpha=.7)
            ax.set_axisbelow(True)
            plt.tight_layout()
            plt.savefig(FIGS / "rq3_runtime_scatter.png", dpi=220)
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


def _parse_cell_runs(protocol: str, rq5_dir: Path, prefix: str,
                     include_all: bool = False) -> dict[str, float] | None:
    """Return {contract: median deployment gas across repeats}, or None if unmeasured.
    include_all=True keeps every gas-reported contract (for a library_embedded subject whose
    production code is only ever deployed inside test/mock harnesses); otherwise strict
    production deployables only."""
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
                if not include_all and not is_production(protocol, e["contract"]):
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
        include_all = is_library_embedded(p)
        cell_maps = {k: _parse_cell_runs(p, rq5_dir, CELLS[k][0], include_all=include_all)
                     for k in CELLS}
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
            "scope": "library-embedded" if include_all else "production",
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
        # the article's fig:rq5: the three factorial comparisons per subject, as
        # deployment-gas reductions on a log scale (they span four orders of magnitude).
        series = [("compiler_alone_pct_A_to_B", "via-IR alone (A→B)", ART_BLUE, "o"),
                  ("gasopt_alone_pct_A_to_C", "gasopt alone, standard optimiser (A→C)", ART_GREEN, "s"),
                  ("gasopt_under_viair_pct_B_to_D", "gasopt on top of via-IR (B→D)", ART_MAGENTA, "D")]
        order = [p for p in ["morpho-blue", "v4-core", "openzeppelin-contracts",
                             "aave-v3-origin", "core", "core-v3"] if p in set(df["protocol"])]
        order += [p for p in df["protocol"] if p not in order]
        byp = df.set_index("protocol")
        with plt.rc_context(ART_RC):
            fig, ax = plt.subplots(figsize=(6.8, 0.55 * len(order) + 1.2))
            for i, p in enumerate(order):
                y = len(order) - 1 - i
                r = byp.loc[p]
                for key, lab, col, mk in series:
                    v = r.get(key)
                    if v is None or pd.isna(v):
                        continue
                    v = abs(float(v))
                    ax.scatter([v], [y], s=46, color=col, marker=mk, zorder=3)
                    txt = f"{v:.4f}%" if v < 0.05 else (f"{v:.2f}%" if v < 1 else f"{v:.1f}%")
                    dy = 8 if key != "gasopt_under_viair_pct_B_to_D" else -15
                    if p == "v4-core":  # avoid clash with the row above
                        dy = -15 if key == "gasopt_alone_pct_A_to_C" else 8
                    ax.annotate(txt, (v, y), textcoords="offset points", xytext=(0, dy),
                                fontsize=7.3, color=ART_INK, ha="center")
                if pd.isna(r.get("compiler_alone_pct_A_to_B")):
                    reason = ("via-IR: stack too deep" if p == "core-v3"
                              else "via-IR: out of memory (31 GiB)")
                    ax.text(90, y, reason, fontsize=7.5, color=ART_INK2,
                            va="center", ha="right", style="italic")
            ax.set_yticks([len(order) - 1 - i for i in range(len(order))])
            ax.set_yticklabels([NICE_NAME.get(p, p) for p in order], fontsize=9)
            ax.set_xscale("log")
            ax.set_xlim(0.0012, 120)
            ax.set_xticks([0.01, 0.1, 1, 10])
            ax.set_xticklabels(["0.01%", "0.1%", "1%", "10%"])
            ax.set_xlabel("deployment-gas reduction, log scale (production contracts, optimizer_runs = 200)")
            ax.legend(handles=[plt.Line2D([], [], marker=mk, color=col, linestyle="",
                                          markersize=7, label=lab)
                               for _, lab, col, mk in series],
                      frameon=False, fontsize=8, loc="lower right", bbox_to_anchor=(1.0, 1.0))
            for s in ["top", "right", "left"]:
                ax.spines[s].set_visible(False)
            ax.grid(axis="x", color=ART_GRID, lw=.6, alpha=.7)
            ax.set_axisbelow(True)
            ax.tick_params(left=False)
            plt.tight_layout()
            plt.savefig(FIGS / "rq5_factorial_pct.png", dpi=220)
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
