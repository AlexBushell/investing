from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_SCENARIO_ID = "msft_cloud_ai_default"
SCENARIO_FILES = {
    DEFAULT_SCENARIO_ID: "msft_default_scenario.json",
    "generic_default": "generic_default.json",
    "psn_housebuilder_default": "psn_housebuilder_default.json",
    "gym_group_default": "gym_group_default.json",
}


def _scenario_path(scenario_id: str) -> Path:
    try:
        return SCENARIO_DIR / SCENARIO_FILES[scenario_id]
    except KeyError as exc:
        raise ValueError(f"Unknown scenario_id: {scenario_id}") from exc


def load_scenario(scenario_id: str) -> dict[str, Any]:
    return json.loads(_scenario_path(scenario_id).read_text(encoding="utf-8"))


def load_default_scenario() -> dict[str, Any]:
    return load_scenario(DEFAULT_SCENARIO_ID)


def list_scenarios() -> list[dict[str, str]]:
    scenarios = []
    for scenario_id in SCENARIO_FILES:
        scenario = load_scenario(scenario_id)
        meta = scenario.get("meta", {})
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "company": str(meta.get("company", scenario_id)),
                "ticker": str(meta.get("ticker", "")),
                "currency": str(meta.get("currency", "")),
                "business_model_type": str(scenario.get("business_model_type", "")),
                "description": str(meta.get("description", "")),
            }
        )
    return scenarios
