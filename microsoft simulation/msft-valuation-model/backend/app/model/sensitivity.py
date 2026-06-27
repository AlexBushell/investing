from __future__ import annotations

from copy import deepcopy

from app.model.assumptions import Scenario
from app.model.distributions import expected_pert_mean
from app.model.simulation import run_simulation


VARIABLE_MUTATORS = {
    "terminal_pe": lambda scenario, factor: _shift_distribution(scenario.valuation.terminal_pe, factor),
    "ai_revenue_growth": lambda scenario, factor: _shift_ai_growth(scenario, factor),
    "gpu_economic_life": lambda scenario, factor: _shift_distribution(scenario.capex.gpu_economic_life_years, factor),
    "shock_probability": lambda scenario, factor: _shift_distribution(scenario.shock.shock_probability, factor),
    "capex_intensity": lambda scenario, factor: _shift_capex_intensity(scenario, factor),
}


def _shift_distribution(spec, factor: float) -> None:
    if spec.type == "fixed":
        spec.value *= factor
        return
    if spec.min is not None:
        spec.min *= factor
    if spec.mode is not None:
        spec.mode *= factor
    if spec.max is not None:
        spec.max *= factor


def _shift_ai_growth(scenario: Scenario, factor: float) -> None:
    for line in scenario.revenue_lines:
        if "AI" not in line.name:
            continue
        _shift_distribution(line.growth.years_1_to_3, factor)
        _shift_distribution(line.growth.years_4_to_7, factor)
        _shift_distribution(line.growth.years_8_to_10, factor)


def _shift_capex_intensity(scenario: Scenario, factor: float) -> None:
    for line in scenario.revenue_lines:
        _shift_distribution(line.capex_intensity.maintenance_pct_of_revenue, factor)
        _shift_distribution(line.capex_intensity.growth_pct_of_incremental_revenue, factor)


def run_sensitivity_analysis(
    scenario: Scenario,
    simulation_count: int,
    random_seed: int | None,
    variables: list[str],
) -> dict:
    base_result = run_simulation(scenario, simulation_count=simulation_count, random_seed=random_seed)
    base_median = base_result["summary"]["median_cagr"]
    items = []

    for variable in variables:
        mutator = VARIABLE_MUTATORS.get(variable)
        if mutator is None:
            continue

        low_scenario = deepcopy(scenario)
        high_scenario = deepcopy(scenario)
        mutator(low_scenario, 0.9)
        mutator(high_scenario, 1.1)

        low_result = run_simulation(low_scenario, simulation_count=simulation_count, random_seed=random_seed)
        high_result = run_simulation(high_scenario, simulation_count=simulation_count, random_seed=random_seed)

        low_case = low_result["summary"]["median_cagr"]
        high_case = high_result["summary"]["median_cagr"]
        impact = high_case - low_case
        items.append(
            {
                "variable": variable,
                "low_case_median_cagr": low_case,
                "base_case_median_cagr": base_median,
                "high_case_median_cagr": high_case,
                "impact": impact,
            }
        )

    items.sort(key=lambda item: abs(item["impact"]), reverse=True)
    return {"items": items}
