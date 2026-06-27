from __future__ import annotations

from copy import deepcopy

from app.business_models.registry import get_business_model
from app.model.assumptions import Scenario
from app.model.simulation import run_simulation


VARIABLE_MUTATORS = {
    "terminal_pe": lambda scenario, factor: _shift_distribution(scenario.valuation.terminal_pe, factor),
    "terminal_fcf_multiple": lambda scenario, factor: _shift_distribution(
        scenario.valuation.terminal_fcf_multiple, factor
    ),
    "terminal_price_to_book": lambda scenario, factor: _shift_optional_distribution(
        scenario.valuation.terminal_price_to_book, factor
    ),
    "terminal_dividend_yield": lambda scenario, factor: _shift_optional_distribution(
        scenario.valuation.terminal_dividend_yield, factor
    ),
    "ai_revenue_growth": lambda scenario, factor: _shift_ai_growth(scenario, factor),
    "gpu_economic_life": lambda scenario, factor: _shift_distribution(scenario.capex.gpu_economic_life_years, factor),
    "shock_probability": lambda scenario, factor: _shift_distribution(scenario.shock.shock_probability, factor),
    "capex_intensity": lambda scenario, factor: _shift_capex_intensity(scenario, factor),
    "generic_revenue_growth": lambda scenario, factor: _shift_generic_revenue_growth(scenario, factor),
    "generic_operating_margin": lambda scenario, factor: _shift_generic_operating_margin(scenario, factor),
    "generic_reinvestment": lambda scenario, factor: _shift_generic_reinvestment(scenario, factor),
    "completions_growth": lambda scenario, factor: _shift_housebuilder_growth(scenario, factor, "completions_growth"),
    "average_selling_price_growth": lambda scenario, factor: _shift_housebuilder_growth(scenario, factor, "asp_growth"),
    "gross_margin": lambda scenario, factor: _shift_housebuilder_gross_margin(scenario, factor),
    "land_reinvestment_pct_revenue": lambda scenario, factor: _shift_business_input_distribution(
        scenario, factor, "land_reinvestment_pct_revenue"
    ),
    "housing_downturn_probability": lambda scenario, factor: _shift_housebuilder_shock_probability(scenario, factor),
    "gym_new_sites": lambda scenario, factor: _shift_gym_new_sites(scenario, factor),
    "gym_revenue_per_site_growth": lambda scenario, factor: _shift_gym_revenue_per_site_growth(scenario, factor),
    "gym_cash_margin": lambda scenario, factor: _shift_gym_cash_margin(scenario, factor),
    "gym_growth_capex": lambda scenario, factor: _shift_business_input_distribution(
        scenario, factor, "growth_capex_per_new_site_bn"
    ),
    "gym_lease_liability": lambda scenario, factor: _shift_business_input_distribution(
        scenario, factor, "lease_liability_per_site_bn"
    ),
    "gym_consumer_squeeze_probability": lambda scenario, factor: _shift_gym_shock_probability(scenario, factor),
}


def _shift_distribution(spec, factor: float) -> None:
    if isinstance(spec, dict):
        if spec.get("type") == "fixed":
            spec["value"] *= factor
            return
        for key in ("min", "mode", "max"):
            if spec.get(key) is not None:
                spec[key] *= factor
        return

    if spec.type == "fixed":
        spec.value *= factor
        return
    if spec.min is not None:
        spec.min *= factor
    if spec.mode is not None:
        spec.mode *= factor
    if spec.max is not None:
        spec.max *= factor


def _shift_optional_distribution(spec, factor: float) -> None:
    if spec is not None:
        _shift_distribution(spec, factor)


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


def _shift_generic_revenue_growth(scenario: Scenario, factor: float) -> None:
    growth = scenario.business_model_inputs.get("revenue_growth", {})
    for period in ("years_1_to_3", "years_4_to_7", "years_8_to_10"):
        if period in growth:
            _shift_distribution(growth[period], factor)


def _shift_generic_operating_margin(scenario: Scenario, factor: float) -> None:
    operating_margin = scenario.business_model_inputs.get("operating_margin", {})
    terminal = operating_margin.get("terminal")
    if terminal is not None:
        _shift_distribution(terminal, factor)


def _shift_generic_reinvestment(scenario: Scenario, factor: float) -> None:
    for key in (
        "maintenance_investment_pct_revenue",
        "growth_investment_pct_incremental_revenue",
        "working_capital_pct_incremental_revenue",
    ):
        if key in scenario.business_model_inputs:
            _shift_distribution(scenario.business_model_inputs[key], factor)


def _shift_business_input_distribution(scenario: Scenario, factor: float, key: str) -> None:
    if key in scenario.business_model_inputs:
        _shift_distribution(scenario.business_model_inputs[key], factor)


def _shift_housebuilder_growth(scenario: Scenario, factor: float, key: str) -> None:
    growth = scenario.business_model_inputs.get(key, {})
    for period in ("years_1_to_3", "years_4_to_7", "years_8_to_10"):
        if period in growth:
            _shift_distribution(growth[period], factor)


def _shift_housebuilder_gross_margin(scenario: Scenario, factor: float) -> None:
    gross_margin = scenario.business_model_inputs.get("gross_margin", {})
    terminal = gross_margin.get("terminal")
    if terminal is not None:
        _shift_distribution(terminal, factor)


def _shift_housebuilder_shock_probability(scenario: Scenario, factor: float) -> None:
    shock = scenario.business_model_inputs.get("housing_downturn_shock", {})
    probability = shock.get("probability")
    if probability is not None:
        _shift_distribution(probability, factor)


def _shift_gym_new_sites(scenario: Scenario, factor: float) -> None:
    new_sites = scenario.business_model_inputs.get("new_sites_per_year", {})
    for period in ("years_1_to_3", "years_4_to_7", "years_8_to_10"):
        if period in new_sites:
            _shift_distribution(new_sites[period], factor)


def _shift_gym_revenue_per_site_growth(scenario: Scenario, factor: float) -> None:
    growth = scenario.business_model_inputs.get("revenue_per_site_growth", {})
    for period in ("years_1_to_3", "years_4_to_7", "years_8_to_10"):
        if period in growth:
            _shift_distribution(growth[period], factor)


def _shift_gym_cash_margin(scenario: Scenario, factor: float) -> None:
    margin = scenario.business_model_inputs.get("cash_ebitda_less_rent_margin", {})
    terminal = margin.get("terminal")
    if terminal is not None:
        _shift_distribution(terminal, factor)


def _shift_gym_shock_probability(scenario: Scenario, factor: float) -> None:
    shock = scenario.business_model_inputs.get("consumer_squeeze_shock", {})
    probability = shock.get("probability")
    if probability is not None:
        _shift_distribution(probability, factor)


def run_sensitivity_analysis(
    scenario: Scenario,
    simulation_count: int,
    random_seed: int | None,
    variables: list[str],
) -> dict:
    base_result = run_simulation(scenario, simulation_count=simulation_count, random_seed=random_seed)
    base_median = base_result["summary"]["median_cagr"]
    supported_variables = set(get_business_model(scenario.business_model_type).sensitivity_variables())
    items = []

    for variable in variables:
        if variable not in supported_variables:
            continue
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
