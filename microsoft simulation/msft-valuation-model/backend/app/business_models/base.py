from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app.model.assumptions import Scenario
from app.model.financials import SimulationArrays


@dataclass
class OperatingModelResult:
    revenue: np.ndarray
    gross_profit: np.ndarray
    operating_profit: np.ndarray
    tax: np.ndarray
    net_income: np.ndarray
    eps: np.ndarray
    operating_cash_flow: np.ndarray
    maintenance_investment: np.ndarray
    growth_investment: np.ndarray
    free_cash_flow: np.ndarray
    dividends: np.ndarray
    dividends_per_share: np.ndarray
    buybacks: np.ndarray
    share_count: np.ndarray
    book_value: np.ndarray | None
    net_debt: np.ndarray | None
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class RegimeDefinition:
    key: str
    label: str
    description: str
    code: int


class BusinessModel(Protocol):
    business_model_type: str

    def validate_inputs(self, scenario: Scenario) -> None:
        ...

    def simulate(
        self,
        scenario: Scenario,
        rng: np.random.Generator,
        simulation_count: int,
    ) -> SimulationArrays:
        ...

    def sensitivity_variables(self) -> list[str]:
        ...

    def regime_definitions(self) -> list[RegimeDefinition]:
        ...

    def default_editor_schema(self) -> dict[str, Any]:
        ...
