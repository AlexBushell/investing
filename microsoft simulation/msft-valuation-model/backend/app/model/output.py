from __future__ import annotations

from typing import Any

import numpy as np

from app.business_models.base import RegimeDefinition
from app.model.assumptions import OutputConfig, RegimeFilter, Scenario
from app.model.distributions import stable_percentile
from app.model.financials import SimulationArrays
from app.model.valuation import build_distribution_from_config


TARGET_RETURN_CONFIDENCE_LEVEL = 0.85


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


def _summary(simulation_arrays: SimulationArrays, scenario: Scenario) -> dict[str, float | int]:
    cagr = simulation_arrays.cagr
    terminal_share_price = simulation_arrays.terminal_share_price
    terminal_eps = simulation_arrays.eps[:, -1]
    terminal_fcf_per_share = simulation_arrays.fcf[:, -1] / simulation_arrays.share_count[:, -1]
    revenue = simulation_arrays.revenue[:, -1]
    target_return_discount_factor = (1.0 + scenario.simulation.target_cagr) ** scenario.simulation.horizon_years
    target_return_entry_prices = simulation_arrays.ending_value_per_share / target_return_discount_factor
    target_return_confidence_price = stable_percentile(
        target_return_entry_prices,
        (1.0 - TARGET_RETURN_CONFIDENCE_LEVEL) * 100.0,
    )

    return {
        "simulation_count": int(cagr.size),
        "target_cagr": scenario.simulation.target_cagr,
        "target_return_confidence_level": TARGET_RETURN_CONFIDENCE_LEVEL,
        "target_return_85_confidence_price": target_return_confidence_price,
        "target_return_85_confidence_price_vs_current": (
            target_return_confidence_price / scenario.market.current_share_price - 1.0
        ),
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


def _confidence_price_curve(simulation_arrays: SimulationArrays, scenario: Scenario) -> dict[str, Any]:
    confidence_percentile = (1.0 - TARGET_RETURN_CONFIDENCE_LEVEL) * 100.0
    ending_value_confidence_floor = max(
        0.01,
        stable_percentile(
            simulation_arrays.ending_value_per_share,
            confidence_percentile,
        ),
    )
    target_return_discount_factor = (1.0 + scenario.simulation.target_cagr) ** scenario.simulation.horizon_years
    target_return_price = ending_value_confidence_floor / target_return_discount_factor
    current_price = scenario.market.current_share_price
    lower_price = max(0.01, min(current_price * 0.55, target_return_price * 0.8))
    upper_price = max(current_price * 1.35, target_return_price * 1.25)
    price_points = np.linspace(lower_price, upper_price, 48)

    points = [
        {
            "entry_price": float(entry_price),
            "confidence_cagr": float(
                (ending_value_confidence_floor / entry_price) ** (1.0 / scenario.simulation.horizon_years) - 1.0
            ),
        }
        for entry_price in price_points
    ]

    return {
        "confidence_level": TARGET_RETURN_CONFIDENCE_LEVEL,
        "target_cagr": scenario.simulation.target_cagr,
        "current_share_price": current_price,
        "target_return_price": target_return_price,
        "ending_value_confidence_floor": ending_value_confidence_floor,
        "points": points,
    }


def _percentiles(simulation_arrays: SimulationArrays, scenario: Scenario) -> list[dict[str, float | int]]:
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


def _fan_chart(simulation_arrays: SimulationArrays) -> list[dict[str, float | int | str]]:
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


def _regime_frequencies(
    simulation_arrays: SimulationArrays,
    regime_definitions: list[RegimeDefinition],
) -> list[dict[str, float | int | str]]:
    return [
        {
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "code": definition.code,
            "frequency": float(np.mean(simulation_arrays.regime_code == definition.code)),
        }
        for definition in regime_definitions
    ]


def _diagnostics(
    simulation_arrays: SimulationArrays,
    regime_definitions: list[RegimeDefinition],
) -> dict[str, Any]:
    diagnostics = {
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
        "regime_frequencies": _regime_frequencies(simulation_arrays, regime_definitions),
    }
    return diagnostics


def build_simulation_output(
    filtered_arrays: SimulationArrays,
    base_arrays: SimulationArrays,
    scenario: Scenario,
    output_config: OutputConfig,
    regime_filter: RegimeFilter,
    regime_definitions: list[RegimeDefinition],
) -> dict[str, Any]:
    distribution = build_distribution_from_config(
        filtered_arrays.cagr,
        target_value=scenario.simulation.target_cagr,
        config=output_config.histogram,
    )

    return {
        "summary": _summary(filtered_arrays, scenario),
        "percentiles": _percentiles(filtered_arrays, scenario),
        "distribution": distribution,
        "confidence_price_curve": _confidence_price_curve(filtered_arrays, scenario),
        "target_marker": {
            "value": scenario.simulation.target_cagr,
            "label": f"{scenario.simulation.target_cagr:.0%} target CAGR",
            "probability_above": distribution["probability_above_target"],
            "probability_below": distribution["probability_below_target"],
        },
        "fan_chart": _fan_chart(filtered_arrays),
        "diagnostics": _diagnostics(base_arrays, regime_definitions),
        "regime_metadata": _regime_frequencies(base_arrays, regime_definitions),
        "regime_filter": regime_filter,
        "base_simulation_count": int(base_arrays.cagr.size),
        "filtered_simulation_count": int(filtered_arrays.cagr.size),
    }
