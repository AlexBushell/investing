from __future__ import annotations

import argparse
import json
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import numpy as np

from app.model.assumptions import OutputConfig, RegimeFilter, Scenario
from app.model.distributions import stable_percentile
from app.model.financials import (
    REGIME_BALANCED,
    REGIME_DISAPPOINTMENT,
    REGIME_OVERBUILD,
    REGIME_SCARCITY,
    SimulationArrays,
    simulate_financials,
)
from app.model.valuation import build_distribution_from_config

DEFAULT_SCENARIO_PATH = Path(__file__).resolve().parents[1] / "data" / "msft_default_scenario.json"
REGIME_FILTER_CODES: dict[RegimeFilter, int | None] = {
    "all": None,
    "scarcity": REGIME_SCARCITY,
    "balanced": REGIME_BALANCED,
    "overbuild": REGIME_OVERBUILD,
    "disappointment": REGIME_DISAPPOINTMENT,
}


def load_default_scenario() -> dict[str, Any]:
    return json.loads(DEFAULT_SCENARIO_PATH.read_text(encoding="utf-8"))


def _fan_chart_metric(name: str, values: np.ndarray) -> list[dict[str, float | int | str]]:
    rows = []
    for year_index in range(values.shape[1]):
        rows.append(
            {
                "year": year_index + 1,
                "metric": name,
                "p10": stable_percentile(values[:, year_index], 10),
                "p25": stable_percentile(values[:, year_index], 25),
                "p50": stable_percentile(values[:, year_index], 50),
                "p75": stable_percentile(values[:, year_index], 75),
                "p90": stable_percentile(values[:, year_index], 90),
            }
        )
    return rows


def _summary(simulation_arrays, scenario: Scenario) -> dict[str, float | int]:
    cagr = simulation_arrays.cagr
    terminal_share_price = simulation_arrays.terminal_share_price
    terminal_eps = simulation_arrays.eps[:, -1]
    terminal_fcf_per_share = simulation_arrays.fcf[:, -1] / simulation_arrays.share_count[:, -1]
    revenue = simulation_arrays.revenue[:, -1]

    return {
        "simulation_count": int(cagr.size),
        "target_cagr": scenario.simulation.target_cagr,
        "probability_above_target": float(np.mean(cagr >= scenario.simulation.target_cagr)),
        "probability_below_target": float(np.mean(cagr < scenario.simulation.target_cagr)),
        "probability_of_loss": float(np.mean(cagr < 0.0)),
        "mean_cagr": float(np.mean(cagr)),
        "median_cagr": stable_percentile(cagr, 50),
        "p10_cagr": stable_percentile(cagr, 10),
        "p25_cagr": stable_percentile(cagr, 25),
        "p50_cagr": stable_percentile(cagr, 50),
        "p75_cagr": stable_percentile(cagr, 75),
        "p90_cagr": stable_percentile(cagr, 90),
        "p95_cagr": stable_percentile(cagr, 95),
        "p10_terminal_share_price": stable_percentile(terminal_share_price, 10),
        "p25_terminal_share_price": stable_percentile(terminal_share_price, 25),
        "p50_terminal_share_price": stable_percentile(terminal_share_price, 50),
        "p75_terminal_share_price": stable_percentile(terminal_share_price, 75),
        "p90_terminal_share_price": stable_percentile(terminal_share_price, 90),
        "p95_terminal_share_price": stable_percentile(terminal_share_price, 95),
        "median_year_10_revenue": stable_percentile(revenue, 50),
        "median_year_10_eps": stable_percentile(terminal_eps, 50),
        "median_year_10_fcf_per_share": stable_percentile(terminal_fcf_per_share, 50),
        "median_terminal_pe": stable_percentile(simulation_arrays.terminal_pe, 50),
        "median_terminal_fcf_multiple": stable_percentile(simulation_arrays.terminal_fcf_multiple, 50),
        "median_total_capex_to_revenue": stable_percentile(
            simulation_arrays.total_capex[:, -1] / np.maximum(simulation_arrays.revenue[:, -1], 1e-9), 50
        ),
        "median_maintenance_capex_to_revenue": stable_percentile(
            simulation_arrays.maintenance_capex[:, -1] / np.maximum(simulation_arrays.revenue[:, -1], 1e-9), 50
        ),
        "median_growth_capex_to_revenue": stable_percentile(
            simulation_arrays.growth_capex[:, -1] / np.maximum(simulation_arrays.revenue[:, -1], 1e-9), 50
        ),
    }


def _percentiles(simulation_arrays, scenario: Scenario) -> list[dict[str, float | int]]:
    cagr = simulation_arrays.cagr
    terminal_share_price = simulation_arrays.terminal_share_price
    terminal_eps = simulation_arrays.eps[:, -1]
    terminal_fcf_per_share = simulation_arrays.fcf[:, -1] / simulation_arrays.share_count[:, -1]
    percentiles = []
    for percentile in (5, 10, 25, 50, 75, 90, 95):
        percentiles.append(
            {
                "percentile": percentile,
                "terminal_share_price": stable_percentile(terminal_share_price, percentile),
                "total_return_multiple": stable_percentile(
                    simulation_arrays.ending_value_per_share / scenario.market.current_share_price,
                    percentile,
                ),
                "cagr": stable_percentile(cagr, percentile),
                "terminal_eps": stable_percentile(terminal_eps, percentile),
                "terminal_pe": stable_percentile(simulation_arrays.terminal_pe, percentile),
                "terminal_fcf_per_share": stable_percentile(terminal_fcf_per_share, percentile),
                "terminal_fcf_multiple": stable_percentile(simulation_arrays.terminal_fcf_multiple, percentile),
            }
        )
    return percentiles


def _fan_chart(simulation_arrays) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    rows.extend(_fan_chart_metric("revenue", simulation_arrays.revenue))
    rows.extend(_fan_chart_metric("operating_income", simulation_arrays.operating_income))
    rows.extend(_fan_chart_metric("net_income", simulation_arrays.net_income))
    rows.extend(_fan_chart_metric("eps", simulation_arrays.eps))
    rows.extend(_fan_chart_metric("fcf", simulation_arrays.fcf))
    rows.extend(_fan_chart_metric("capex", simulation_arrays.total_capex))
    rows.extend(_fan_chart_metric("maintenance_capex", simulation_arrays.maintenance_capex))
    rows.extend(_fan_chart_metric("growth_capex", simulation_arrays.growth_capex))
    rows.extend(_fan_chart_metric("share_count", simulation_arrays.share_count))
    rows.extend(_fan_chart_metric("gross_margin", simulation_arrays.total_gross_margin))
    rows.extend(_fan_chart_metric("operating_margin", simulation_arrays.operating_margin))
    return rows


def _diagnostics(simulation_arrays) -> dict[str, float]:
    return {
        "median_year_10_revenue_bn": stable_percentile(simulation_arrays.revenue[:, -1], 50),
        "median_year_10_eps": stable_percentile(simulation_arrays.eps[:, -1], 50),
        "median_year_10_fcf_per_share": stable_percentile(
            simulation_arrays.fcf[:, -1] / np.maximum(simulation_arrays.share_count[:, -1], 1e-9),
            50,
        ),
        "median_capex_to_revenue": stable_percentile(
            simulation_arrays.total_capex[:, -1] / np.maximum(simulation_arrays.revenue[:, -1], 1e-9),
            50,
        ),
        "median_maintenance_capex_to_revenue": stable_percentile(
            simulation_arrays.maintenance_capex[:, -1] / np.maximum(simulation_arrays.revenue[:, -1], 1e-9),
            50,
        ),
        "median_growth_capex_to_revenue": stable_percentile(
            simulation_arrays.growth_capex[:, -1] / np.maximum(simulation_arrays.revenue[:, -1], 1e-9),
            50,
        ),
        "shock_frequency_realised": float(np.mean(simulation_arrays.shock_occurs)),
        "accelerated_depreciation_frequency_realised": float(
            np.mean(simulation_arrays.accelerated_depreciation_occurs)
        ),
        "regime_frequency_scarcity": float(np.mean(simulation_arrays.regime_code == 0)),
        "regime_frequency_balanced": float(np.mean(simulation_arrays.regime_code == 1)),
        "regime_frequency_overbuild": float(np.mean(simulation_arrays.regime_code == 2)),
        "regime_frequency_disappointment": float(np.mean(simulation_arrays.regime_code == 3)),
    }


def _apply_regime_filter(simulation_arrays: SimulationArrays, regime_filter: RegimeFilter) -> SimulationArrays:
    regime_code = REGIME_FILTER_CODES[regime_filter]
    if regime_code is None:
        return simulation_arrays

    mask = simulation_arrays.regime_code == regime_code
    if not np.any(mask):
        raise ValueError(f"No simulations matched regime filter: {regime_filter}")

    updates = {field.name: getattr(simulation_arrays, field.name)[mask] for field in fields(simulation_arrays)}
    return replace(simulation_arrays, **updates)


def run_simulation(
    scenario: Scenario,
    simulation_count: int | None = None,
    random_seed: int | None = None,
    output_config: OutputConfig | None = None,
    regime_filter: RegimeFilter = "all",
) -> dict[str, Any]:
    runs = simulation_count or scenario.simulation.simulation_count
    seed = random_seed if random_seed is not None else scenario.simulation.random_seed
    rng = np.random.default_rng(seed)
    arrays = simulate_financials(scenario, runs, rng)
    filtered_arrays = _apply_regime_filter(arrays, regime_filter)

    output = output_config or OutputConfig()
    distribution = build_distribution_from_config(
        filtered_arrays.cagr,
        target_value=scenario.simulation.target_cagr,
        config=output.histogram,
    )

    return {
        "summary": _summary(filtered_arrays, scenario),
        "percentiles": _percentiles(filtered_arrays, scenario),
        "distribution": distribution,
        "target_marker": {
            "value": scenario.simulation.target_cagr,
            "label": f"{scenario.simulation.target_cagr:.0%} target CAGR",
            "probability_above": distribution["probability_above_target"],
            "probability_below": distribution["probability_below_target"],
        },
        "fan_chart": _fan_chart(filtered_arrays),
        "diagnostics": _diagnostics(arrays),
        "regime_filter": regime_filter,
        "base_simulation_count": int(arrays.cagr.size),
        "filtered_simulation_count": int(filtered_arrays.cagr.size),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MSFT valuation simulation")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    scenario_data = json.loads(args.scenario.read_text(encoding="utf-8"))
    scenario = Scenario.model_validate(scenario_data)
    result = run_simulation(scenario, simulation_count=args.runs, random_seed=args.seed)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
