from __future__ import annotations

import argparse
import json
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import numpy as np

from app.business_models.base import RegimeDefinition
from app.business_models.registry import get_business_model
from app.model.assumptions import OutputConfig, RegimeFilter, Scenario
from app.model.financials import SimulationArrays
from app.model.output import build_simulation_output
from app.model.scenarios import load_default_scenario

def _apply_regime_filter(
    simulation_arrays: SimulationArrays,
    regime_filter: RegimeFilter,
    regime_definitions: list[RegimeDefinition],
) -> SimulationArrays:
    if regime_filter == "all":
        return simulation_arrays
    regime_codes = {definition.key: definition.code for definition in regime_definitions}
    try:
        regime_code = regime_codes[regime_filter]
    except KeyError as exc:
        supported = ", ".join(["all", *(definition.key for definition in regime_definitions)])
        raise ValueError(f"Unsupported regime filter '{regime_filter}'. Supported filters: {supported}") from exc

    mask = simulation_arrays.regime_code == regime_code
    if not np.any(mask):
        raise ValueError(f"No simulations matched regime filter: {regime_filter}")

    updates = {field.name: getattr(simulation_arrays, field.name)[mask] for field in fields(simulation_arrays)}
    return replace(simulation_arrays, **updates)


def run_simulation(
    scenario: Scenario,
    simulation_count: int | None = None,
    random_seed: int | None = None,
    output_config: OutputConfig | None = None,
    regime_filter: RegimeFilter = "all",
) -> dict[str, Any]:
    runs = simulation_count or scenario.simulation.simulation_count
    seed = random_seed if random_seed is not None else scenario.simulation.random_seed
    rng = np.random.default_rng(seed)
    business_model = get_business_model(scenario.business_model_type)
    regime_definitions = business_model.regime_definitions()
    arrays = business_model.simulate(scenario, rng, runs)
    filtered_arrays = _apply_regime_filter(arrays, regime_filter, regime_definitions)

    return build_simulation_output(
        filtered_arrays=filtered_arrays,
        base_arrays=arrays,
        scenario=scenario,
        output_config=output_config or OutputConfig(),
        regime_filter=regime_filter,
        regime_definitions=regime_definitions,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MSFT valuation simulation")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    scenario_data = json.loads(args.scenario.read_text(encoding="utf-8"))
    scenario = Scenario.model_validate(scenario_data)
    result = run_simulation(scenario, simulation_count=args.runs, random_seed=args.seed)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
