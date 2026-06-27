import pytest

from app.business_models.registry import get_business_model, list_business_models
from app.model.assumptions import Scenario
from app.model.simulation import load_default_scenario, run_simulation


def test_registry_resolves_cloud_ai_model() -> None:
    model = get_business_model("cloud_software_ai_infrastructure")

    assert model.business_model_type == "cloud_software_ai_infrastructure"
    assert "terminal_pe" in model.sensitivity_variables()
    assert "cloud_software_ai_infrastructure" in list_business_models()
    assert "generic_revenue_margin_fcf" in list_business_models()


def test_registry_resolves_generic_model() -> None:
    model = get_business_model("generic_revenue_margin_fcf")

    assert model.business_model_type == "generic_revenue_margin_fcf"
    assert "generic_revenue_growth" in model.sensitivity_variables()


def test_registry_resolves_housebuilder_model() -> None:
    model = get_business_model("housebuilder")

    assert model.business_model_type == "housebuilder"
    assert "terminal_price_to_book" in model.sensitivity_variables()
    assert "housebuilder" in list_business_models()


def test_registry_resolves_low_cost_gym_model() -> None:
    model = get_business_model("low_cost_gym_ifrs16")

    assert model.business_model_type == "low_cost_gym_ifrs16"
    assert "gym_lease_liability" in model.sensitivity_variables()
    assert "low_cost_gym_ifrs16" in list_business_models()


def test_registry_rejects_unknown_model() -> None:
    with pytest.raises(ValueError, match="Unsupported business_model_type"):
        get_business_model("unknown_model")


def test_default_scenario_runs_through_registered_business_model() -> None:
    scenario = Scenario.model_validate(load_default_scenario())
    result = run_simulation(scenario, simulation_count=1000, random_seed=42)

    assert scenario.business_model_type == "cloud_software_ai_infrastructure"
    assert result["summary"]["simulation_count"] == 1000
    assert result["distribution"]["metric"] == "total_return_cagr"
