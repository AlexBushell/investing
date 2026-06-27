import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.model.assumptions import Scenario
from app.model.simulation import load_default_scenario, run_simulation


def test_default_scenario_runs_without_nan() -> None:
    scenario = Scenario.model_validate(load_default_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42)

    assert result["summary"]["simulation_count"] == 1000
    assert "distribution" in result
    probabilities = [bucket["probability"] for bucket in result["distribution"]["buckets"]]
    cumulative = [bucket["cumulative_probability"] for bucket in result["distribution"]["buckets"]]
    assert abs(sum(probabilities) - 1.0) < 1e-9
    assert all(left <= right + 1e-12 for left, right in zip(cumulative, cumulative[1:]))
    assert np.isfinite(result["summary"]["median_cagr"])
    assert result["distribution"]["confidence_floor"]["confidence_level"] == 0.85
    assert 0.84 <= result["distribution"]["confidence_floor"]["probability_at_or_above"] <= 0.86
    regime_total = (
        result["diagnostics"]["regime_frequency_scarcity"]
        + result["diagnostics"]["regime_frequency_balanced"]
        + result["diagnostics"]["regime_frequency_overbuild"]
        + result["diagnostics"]["regime_frequency_disappointment"]
    )
    assert abs(regime_total - 1.0) < 1e-9


def test_regime_filter_returns_conditional_distribution() -> None:
    scenario = Scenario.model_validate(load_default_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42, regime_filter="balanced")

    assert result["regime_filter"] == "balanced"
    assert result["base_simulation_count"] == 1000
    assert 0 < result["filtered_simulation_count"] < result["base_simulation_count"]
    assert result["summary"]["simulation_count"] == result["filtered_simulation_count"]
    assert abs(sum(bucket["probability"] for bucket in result["distribution"]["buckets"]) - 1.0) < 1e-9


def test_simulate_api_accepts_regime_filter() -> None:
    client = TestClient(app)
    scenario = load_default_scenario()

    response = client.post(
        "/api/simulate",
        json={
            "scenario": scenario,
            "simulation_count": 1000,
            "random_seed": 42,
            "regime_filter": "balanced",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["regime_filter"] == "balanced"
    assert payload["base_simulation_count"] == 1000
    assert 0 < payload["filtered_simulation_count"] < payload["base_simulation_count"]
    assert payload["summary"]["simulation_count"] == payload["filtered_simulation_count"]
