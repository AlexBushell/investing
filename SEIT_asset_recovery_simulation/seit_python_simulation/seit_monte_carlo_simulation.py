
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import json
import math

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


@dataclass(frozen=True)
class GlobalInputs:
    equity_nav_per_share_p: float
    entry_price_as_pct_nav: float
    gross_assets_multiple_nav: float
    debt_multiple_nav: float
    wind_down_costs_low: float
    wind_down_costs_mode: float
    wind_down_costs_high: float
    financing_drag_low: float
    financing_drag_mode: float
    financing_drag_high: float
    dividend_yield_low: float
    dividend_yield_mode: float
    dividend_yield_high: float
    tax_leakage_low: float
    tax_leakage_mode: float
    tax_leakage_high: float


def _as_float(value: Any, default: float | None = None) -> float:
    if value in ("", None):
        if default is None:
            raise ValueError("Missing numeric value")
        return default
    return float(value)


def _find_global(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for row in rows:
        if row.get("Input") == name:
            return row
    raise KeyError(f"Global input not found: {name}")


def _global_tri(rows: list[dict[str, Any]], name: str) -> tuple[float, float, float]:
    row = _find_global(rows, name)
    return (
        _as_float(row.get("Low")),
        _as_float(row.get("Mode/Base")),
        _as_float(row.get("High")),
    )


def load_inputs(json_path: str | Path) -> tuple[GlobalInputs, pd.DataFrame, dict[str, Any]]:
    json_path = Path(json_path)
    with json_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    global_rows = config["global_inputs"]

    wind_low, wind_mode, wind_high = _global_tri(global_rows, "wind_down_costs_pct_nav_total")
    fin_low, fin_mode, fin_high = _global_tri(global_rows, "financing_drag_pct_nav_per_year")
    div_low, div_mode, div_high = _global_tri(global_rows, "dividend_cash_yield_pct_nav_per_year")
    tax_low, tax_mode, tax_high = _global_tri(global_rows, "tax_leakage_pct_nav_total")

    g = GlobalInputs(
        equity_nav_per_share_p=_as_float(_find_global(global_rows, "equity_nav_per_share_p").get("Value")),
        entry_price_as_pct_nav=_as_float(_find_global(global_rows, "entry_price_as_pct_nav").get("Value")),
        gross_assets_multiple_nav=_as_float(_find_global(global_rows, "gross_assets_multiple_nav").get("Value")),
        debt_multiple_nav=_as_float(_find_global(global_rows, "debt_multiple_nav").get("Value")),
        wind_down_costs_low=wind_low,
        wind_down_costs_mode=wind_mode,
        wind_down_costs_high=wind_high,
        financing_drag_low=fin_low,
        financing_drag_mode=fin_mode,
        financing_drag_high=fin_high,
        dividend_yield_low=div_low,
        dividend_yield_mode=div_mode,
        dividend_yield_high=div_high,
        tax_leakage_low=tax_low,
        tax_leakage_mode=tax_mode,
        tax_leakage_high=tax_high,
    )

    assets = pd.DataFrame(config["asset_inputs"]).copy()
    numeric_cols = [
        "Indicative gross asset weight",
        "Recovery low",
        "Recovery mode",
        "Recovery high",
        "Timing low yrs",
        "Timing mode yrs",
        "Timing high yrs",
        "Systematic beta",
        "Idio sigma",
    ]
    for col in numeric_cols:
        assets[col] = pd.to_numeric(assets[col], errors="raise")

    weight_sum = assets["Indicative gross asset weight"].sum()
    if not math.isclose(weight_sum, 1.0, abs_tol=0.02):
        raise ValueError(f"Asset weights should sum to ~1.0, but sum to {weight_sum:.4f}")
    assets["weight_norm"] = assets["Indicative gross asset weight"] / weight_sum
    return g, assets, config


def triangular(rng: np.random.Generator, low: float, mode: float, high: float, n: int) -> np.ndarray:
    return rng.triangular(left=low, mode=mode, right=high, size=n)


def beta_pert(
    rng: np.random.Generator,
    low: float,
    mode: float,
    high: float,
    n: int,
    lamb: float = 4.0,
) -> np.ndarray:
    if high < low:
        raise ValueError(f"Invalid bounds for beta_pert: low={low}, high={high}")
    if not (low <= mode <= high):
        raise ValueError(f"Mode must lie within [low, high] for beta_pert: {mode}")
    if math.isclose(high, low):
        return np.full(n, low, dtype=float)

    span = high - low
    alpha = 1.0 + lamb * (mode - low) / span
    beta = 1.0 + lamb * (high - mode) / span
    return low + rng.beta(alpha, beta, size=n) * span


def sample_distribution(
    rng: np.random.Generator,
    distribution: str,
    low: float,
    mode: float,
    high: float,
    n: int,
) -> np.ndarray:
    distribution = distribution.strip().lower()
    if distribution == "triangular":
        return triangular(rng, low, mode, high, n)
    if distribution in {"beta_pert", "pert", "beta-pert"}:
        return beta_pert(rng, low, mode, high, n)
    if distribution == "uniform":
        return rng.uniform(low=low, high=high, size=n)
    if distribution == "fixed":
        return np.full(n, mode, dtype=float)
    raise ValueError(
        "Unsupported distribution "
        f"'{distribution}'. Supported values: triangular, beta_pert, uniform, fixed."
    )


def run_simulation(
    json_path: str | Path,
    n_sims: int = 100_000,
    seed: int = 42,
    entry_price_as_pct_nav: float | None = None,
    systematic_shock_scale: float = 0.05,
    clamp_recovery_low: float = 0.0,
    clamp_recovery_high: float = 1.10,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    g, assets, _ = load_inputs(json_path)
    if entry_price_as_pct_nav is None:
        entry_price_as_pct_nav = g.entry_price_as_pct_nav

    rng = np.random.default_rng(seed)
    z_systematic = rng.normal(0.0, 1.0, size=n_sims)

    weighted_gross_recovery = np.zeros(n_sims)
    weighted_duration = np.zeros(n_sims)
    asset_summary_rows = []

    for _, asset in assets.iterrows():
        weight = float(asset["weight_norm"])
        base_recovery = sample_distribution(
            rng,
            str(asset.get("Recovery distribution", "triangular")),
            float(asset["Recovery low"]),
            float(asset["Recovery mode"]),
            float(asset["Recovery high"]),
            n_sims,
        )
        idio = rng.normal(0.0, 1.0, size=n_sims) * float(asset["Idio sigma"])
        recovery = base_recovery + float(asset["Systematic beta"]) * systematic_shock_scale * z_systematic + idio
        recovery = np.clip(recovery, clamp_recovery_low, clamp_recovery_high)

        timing = sample_distribution(
            rng,
            str(asset.get("Orderly sale timing distribution", "triangular")),
            float(asset["Timing low yrs"]),
            float(asset["Timing mode yrs"]),
            float(asset["Timing high yrs"]),
            n_sims,
        )

        weighted_gross_recovery += weight * recovery
        weighted_duration += weight * timing

        asset_summary_rows.append(
            {
                "asset": asset["Asset Bucket"],
                "weight": weight,
                "mean_recovery": recovery.mean(),
                "p10_recovery": np.quantile(recovery, 0.10),
                "p50_recovery": np.quantile(recovery, 0.50),
                "p90_recovery": np.quantile(recovery, 0.90),
                "mean_timing_years": timing.mean(),
                "p50_timing_years": np.quantile(timing, 0.50),
                "mean_weighted_recovery_contribution": weight * recovery.mean(),
            }
        )

    wind_down_costs = triangular(rng, g.wind_down_costs_low, g.wind_down_costs_mode, g.wind_down_costs_high, n_sims)
    tax_leakage = triangular(rng, g.tax_leakage_low, g.tax_leakage_mode, g.tax_leakage_high, n_sims)
    financing_drag_annual = triangular(rng, g.financing_drag_low, g.financing_drag_mode, g.financing_drag_high, n_sims)
    dividend_yield_annual = triangular(rng, g.dividend_yield_low, g.dividend_yield_mode, g.dividend_yield_high, n_sims)

    financing_drag = financing_drag_annual * weighted_duration
    dividends_received = dividend_yield_annual * weighted_duration

    equity_recovery_before_leakage = weighted_gross_recovery * g.gross_assets_multiple_nav - g.debt_multiple_nav

    shareholder_recovery_pct_nav = (
        equity_recovery_before_leakage
        - wind_down_costs
        - tax_leakage
        - financing_drag
        + dividends_received
    )

    total_return = shareholder_recovery_pct_nav / entry_price_as_pct_nav - 1.0
    recovery_p_per_share = shareholder_recovery_pct_nav * g.equity_nav_per_share_p
    entry_price_p = entry_price_as_pct_nav * g.equity_nav_per_share_p

    results = pd.DataFrame(
        {
            "weighted_gross_recovery": weighted_gross_recovery,
            "weighted_duration_years": weighted_duration,
            "equity_recovery_before_leakage_pct_nav": equity_recovery_before_leakage,
            "wind_down_costs_pct_nav": wind_down_costs,
            "tax_leakage_pct_nav": tax_leakage,
            "financing_drag_pct_nav": financing_drag,
            "dividends_received_pct_nav": dividends_received,
            "shareholder_recovery_pct_nav": shareholder_recovery_pct_nav,
            "recovery_p_per_share": recovery_p_per_share,
            "entry_price_p": entry_price_p,
            "total_return": total_return,
        }
    )

    asset_summary = pd.DataFrame(asset_summary_rows).sort_values(
        "mean_weighted_recovery_contribution", ascending=False
    )
    return results, asset_summary, assets


def summarise_results(results: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "weighted_gross_recovery",
        "weighted_duration_years",
        "equity_recovery_before_leakage_pct_nav",
        "shareholder_recovery_pct_nav",
        "recovery_p_per_share",
        "total_return",
    ]
    summary = []
    for col in cols:
        s = results[col]
        summary.append(
            {
                "metric": col,
                "mean": s.mean(),
                "p05": s.quantile(0.05),
                "p10": s.quantile(0.10),
                "p25": s.quantile(0.25),
                "p50": s.quantile(0.50),
                "p75": s.quantile(0.75),
                "p90": s.quantile(0.90),
                "p95": s.quantile(0.95),
                "probability_positive": (s > 0).mean() if col == "total_return" else np.nan,
                "probability_gt_20pct": (s > 0.20).mean() if col == "total_return" else np.nan,
                "probability_loss_gt_20pct": (s < -0.20).mean() if col == "total_return" else np.nan,
            }
        )
    return pd.DataFrame(summary)


def make_charts(results: pd.DataFrame, output_dir: str | Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_paths = []

    plt.figure()
    plt.hist(results["total_return"], bins=80)
    plt.xlabel("Total return")
    plt.ylabel("Simulation count")
    plt.title("SEIT simulated total return distribution")
    path = output_dir / "seit_total_return_histogram.png"
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    chart_paths.append(path)

    plt.figure()
    plt.hist(results["weighted_gross_recovery"], bins=80)
    plt.xlabel("Weighted gross asset recovery")
    plt.ylabel("Simulation count")
    plt.title("SEIT weighted gross asset recovery distribution")
    path = output_dir / "seit_gross_recovery_histogram.png"
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    chart_paths.append(path)

    sample = results.sample(min(8000, len(results)), random_state=1)
    plt.figure()
    plt.scatter(sample["weighted_gross_recovery"], sample["total_return"], s=3, alpha=0.25)
    plt.xlabel("Weighted gross asset recovery")
    plt.ylabel("Total return")
    plt.title("SEIT gross recovery vs total return")
    path = output_dir / "seit_gross_recovery_vs_total_return.png"
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    chart_paths.append(path)

    return chart_paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True)
    parser.add_argument("--n-sims", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--entry-price-pct-nav", type=float, default=None)
    parser.add_argument("--output-dir", default="seit_simulation_output")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results, asset_summary, assets = run_simulation(
        json_path=args.json,
        n_sims=args.n_sims,
        seed=args.seed,
        entry_price_as_pct_nav=args.entry_price_pct_nav,
    )
    summary = summarise_results(results)

    results.to_csv(output_dir / "simulation_results.csv", index=False)
    summary.to_csv(output_dir / "simulation_summary.csv", index=False)
    asset_summary.to_csv(output_dir / "asset_recovery_summary.csv", index=False)
    assets.to_csv(output_dir / "asset_inputs_used.csv", index=False)
    chart_paths = make_charts(results, output_dir)

    print("Simulation complete")
    print(f"Simulations: {args.n_sims:,}")
    print(f"Output directory: {output_dir.resolve()}")
    print(summary.to_string(index=False))
    print("Charts:")
    for path in chart_paths:
        print(path)


if __name__ == "__main__":
    main()
