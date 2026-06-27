import json
from pathlib import Path

import numpy as np

from app.model.assumptions import Scenario
from app.model.sensitivity import run_sensitivity_analysis
from app.model.simulation import run_simulation


HOUSEBUILDER_SCENARIO_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "psn_housebuilder_default.json"
)


def load_housebuilder_scenario() -> dict:
    return json.loads(HOUSEBUILDER_SCENARIO_PATH.read_text(encoding="utf-8"))


def test_housebuilder_scenario_runs() -> None:
    scenario = Scenario.model_validate(load_housebuilder_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42)

    assert scenario.business_model_type == "housebuilder"
    assert result["summary"]["simulation_count"] == 1000
    assert result["distribution"]["metric"] == "total_return_cagr"
    assert len(result["confidence_price_curve"]["points"]) == 48
    assert np.isfinite(result["summary"]["median_cagr"])
    assert result["summary"]["target_return_85_confidence_price"] > 0
    assert result["summary"]["median_year_10_fcf_per_share"] > 0
    assert result["summary"]["median_maintenance_capex_to_revenue"] > 0
    assert result["diagnostics"]["regime_frequency_balanced"] > 0
    assert result["diagnostics"]["regime_frequency_disappointment"] > 0
    assert {item["key"] for item in result["regime_metadata"]} == {
        "recovery",
        "steady_cycle",
        "housing_downturn",
        "land_margin_stress",
    }
    assert any(item["label"] == "Housing downturn" for item in result["regime_metadata"])
    assert abs(sum(item["frequency"] for item in result["regime_metadata"]) - 1.0) < 1e-9


def test_housebuilder_regime_filter_uses_housebuilder_keys() -> None:
    scenario = Scenario.model_validate(load_housebuilder_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42, regime_filter="housing_downturn")

    assert result["regime_filter"] == "housing_downturn"
    assert 0 < result["filtered_simulation_count"] < result["base_simulation_count"]
    assert result["summary"]["simulation_count"] == result["filtered_simulation_count"]


def test_housebuilder_sensitivity_uses_housebuilder_variables() -> None:
    scenario = Scenario.model_validate(load_housebuilder_scenario())
    result = run_sensitivity_analysis(
        scenario,
        simulation_count=500,
        random_seed=42,
        variables=[
            "terminal_price_to_book",
            "terminal_dividend_yield",
            "completions_growth",
            "average_selling_price_growth",
            "gross_margin",
            "housing_downturn_probability",
            "generic_revenue_growth",
        ],
    )

    variables = {item["variable"] for item in result["items"]}
    assert "terminal_price_to_book" in variables
    assert "terminal_dividend_yield" in variables
    assert "completions_growth" in variables
    assert "average_selling_price_growth" in variables
    assert "gross_margin" in variables
    assert "housing_downturn_probability" in variables
    assert "generic_revenue_growth" not in variables
