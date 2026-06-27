import json
from pathlib import Path

import numpy as np

from app.model.assumptions import Scenario
from app.model.sensitivity import run_sensitivity_analysis
from app.model.simulation import run_simulation


GYM_SCENARIO_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "gym_group_default.json"


def load_gym_scenario() -> dict:
    return json.loads(GYM_SCENARIO_PATH.read_text(encoding="utf-8"))


def test_low_cost_gym_scenario_runs() -> None:
    scenario = Scenario.model_validate(load_gym_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42)

    assert scenario.business_model_type == "low_cost_gym_ifrs16"
    assert result["summary"]["simulation_count"] == 1000
    assert result["distribution"]["metric"] == "total_return_cagr"
    assert len(result["confidence_price_curve"]["points"]) == 48
    assert np.isfinite(result["summary"]["median_cagr"])
    assert result["summary"]["median_year_10_fcf_per_share"] > 0
    assert result["summary"]["median_growth_capex_to_revenue"] > 0
    assert {item["key"] for item in result["regime_metadata"]} == {
        "expansion_compounding",
        "steady_rollout",
        "lease_leverage_pressure",
        "consumer_squeeze",
    }


def test_low_cost_gym_regime_filter_uses_gym_keys() -> None:
    scenario = Scenario.model_validate(load_gym_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42, regime_filter="consumer_squeeze")

    assert result["regime_filter"] == "consumer_squeeze"
    assert 0 < result["filtered_simulation_count"] <= result["base_simulation_count"]


def test_low_cost_gym_sensitivity_uses_gym_variables() -> None:
    scenario = Scenario.model_validate(load_gym_scenario())
    result = run_sensitivity_analysis(
        scenario,
        simulation_count=500,
        random_seed=42,
        variables=[
            "terminal_pe",
            "terminal_fcf_multiple",
            "gym_new_sites",
            "gym_revenue_per_site_growth",
            "gym_cash_margin",
            "gym_growth_capex",
            "gym_lease_liability",
            "gym_consumer_squeeze_probability",
            "completions_growth",
        ],
    )

    variables = {item["variable"] for item in result["items"]}
    assert "terminal_pe" in variables
    assert "terminal_fcf_multiple" in variables
    assert "gym_new_sites" in variables
    assert "gym_revenue_per_site_growth" in variables
    assert "gym_cash_margin" in variables
    assert "gym_growth_capex" in variables
    assert "gym_lease_liability" in variables
    assert "gym_consumer_squeeze_probability" in variables
    assert "completions_growth" not in variables
