from __future__ import annotations

from typing import Any

import numpy as np

from app.model.assumptions import Scenario
from app.business_models.base import RegimeDefinition
from app.model.financials import (
    REGIME_BALANCED,
    REGIME_DISAPPOINTMENT,
    REGIME_OVERBUILD,
    REGIME_SCARCITY,
    SimulationArrays,
    simulate_financials,
)


class CloudSoftwareAiInfrastructureModel:
    business_model_type = "cloud_software_ai_infrastructure"

    def validate_inputs(self, scenario: Scenario) -> None:
        if scenario.base_financials is None:
            raise ValueError("cloud/software/AI model requires base_financials")
        if not scenario.revenue_lines:
            raise ValueError("cloud/software/AI model requires at least one revenue line")
        if scenario.opex is None:
            raise ValueError("cloud/software/AI model requires opex")
        if scenario.capex is None:
            raise ValueError("cloud/software/AI model requires capex")
        if scenario.shock is None:
            raise ValueError("cloud/software/AI model requires shock")

    def simulate(
        self,
        scenario: Scenario,
        rng: np.random.Generator,
        simulation_count: int,
    ) -> SimulationArrays:
        self.validate_inputs(scenario)
        return simulate_financials(scenario, simulation_count, rng)

    def sensitivity_variables(self) -> list[str]:
        return [
            "terminal_pe",
            "ai_revenue_growth",
            "gpu_economic_life",
            "shock_probability",
            "capex_intensity",
        ]

    def regime_definitions(self) -> list[RegimeDefinition]:
        return [
            RegimeDefinition(
                key="scarcity",
                label="AI scarcity / high ROI",
                description="Strong AI demand, better margins, and supportive terminal valuation.",
                code=REGIME_SCARCITY,
            ),
            RegimeDefinition(
                key="balanced",
                label="Balanced growth",
                description="More normal demand, capex, and valuation outcomes.",
                code=REGIME_BALANCED,
            ),
            RegimeDefinition(
                key="overbuild",
                label="Overbuild / price compression",
                description="High buildout, weaker utilization, and valuation pressure.",
                code=REGIME_OVERBUILD,
            ),
            RegimeDefinition(
                key="disappointment",
                label="AI disappointment",
                description="Slower AI monetization with weaker growth and margin support.",
                code=REGIME_DISAPPOINTMENT,
            ),
        ]

    def default_editor_schema(self) -> dict[str, Any]:
        return {
            "common": ["market", "simulation", "valuation", "capital_return", "histogram"],
            "business_specific": ["revenue_lines", "opex", "capex", "shock"],
        }
