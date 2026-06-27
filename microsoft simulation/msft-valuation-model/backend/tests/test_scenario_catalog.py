from fastapi.testclient import TestClient

from app.main import app
from app.model.scenarios import list_scenarios, load_scenario


def test_scenario_catalog_lists_default_scenarios() -> None:
    scenarios = list_scenarios()
    scenario_ids = {scenario["scenario_id"] for scenario in scenarios}

    assert "msft_cloud_ai_default" in scenario_ids
    assert "generic_default" in scenario_ids
    assert "psn_housebuilder_default" in scenario_ids
    assert "gym_group_default" in scenario_ids


def test_load_generic_scenario_by_id() -> None:
    scenario = load_scenario("generic_default")

    assert scenario["business_model_type"] == "generic_revenue_margin_fcf"
    assert scenario["meta"]["ticker"] == "GEN"


def test_scenario_catalog_api() -> None:
    client = TestClient(app)

    scenarios_response = client.get("/api/scenarios")
    assert scenarios_response.status_code == 200
    assert {scenario["scenario_id"] for scenario in scenarios_response.json()} >= {
        "msft_cloud_ai_default",
        "generic_default",
        "psn_housebuilder_default",
        "gym_group_default",
    }

    scenario_response = client.get("/api/scenarios/generic_default")
    assert scenario_response.status_code == 200
    assert scenario_response.json()["business_model_type"] == "generic_revenue_margin_fcf"


def test_unknown_scenario_returns_404() -> None:
    client = TestClient(app)

    response = client.get("/api/scenarios/nope")

    assert response.status_code == 404
