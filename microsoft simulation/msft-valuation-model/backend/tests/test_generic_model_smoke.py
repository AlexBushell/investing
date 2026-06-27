import json
from pathlib import Path

import numpy as np

from app.model.assumptions import Scenario
from app.model.sensitivity import run_sensitivity_analysis
from app.model.simulation import run_simulation


GENERIC_SCENARIO_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "generic_default.json"


def load_generic_scenario() -> dict:
    return json.loads(GENERIC_SCENARIO_PATH.read_text(encoding="utf-8"))


def test_generic_revenue_margin_fcf_scenario_runs() -> None:
    scenario = Scenario.model_validate(load_generic_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42)

    assert scenario.business_model_type == "generic_revenue_margin_fcf"
    assert result["summary"]["simulation_count"] == 1000
    assert result["distribution"]["metric"] == "total_return_cagr"
    assert len(result["percentiles"]) == 7
    assert len(result["confidence_price_curve"]["points"]) == 48
    assert np.isfinite(result["summary"]["median_cagr"])
    assert result["summary"]["target_return_85_confidence_price"] > 0
    regime_freqs = {item["key"]: item["frequency"] for item in result["diagnostics"]["regime_frequencies"]}
    assert regime_freqs["balanced"] == 1.0
    assert result["diagnostics"]["shock_frequency_realised"] == 0.0


def test_generic_model_supports_regime_all_filter() -> None:
    scenario = Scenario.model_validate(load_generic_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42, regime_filter="all")

    assert result["base_simulation_count"] == 1000
    assert result["filtered_simulation_count"] == 1000
    assert abs(sum(bucket["probability"] for bucket in result["distribution"]["buckets"]) - 1.0) < 1e-9


def test_generic_model_sensitivity_uses_generic_variables() -> None:
    scenario = Scenario.model_validate(load_generic_scenario())
    result = run_sensitivity_analysis(
        scenario,
        simulation_count=500,
        random_seed=42,
        variables=[
            "terminal_pe",
            "generic_revenue_growth",
            "generic_operating_margin",
            "generic_reinvestment",
            "gpu_economic_life",
        ],
    )

    variables = {item["variable"] for item in result["items"]}
    assert "terminal_pe" in variables
    assert "generic_revenue_growth" in variables
    assert "generic_operating_margin" in variables
    assert "generic_reinvestment" in variables
    assert "gpu_economic_life" not in variables
