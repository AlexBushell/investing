from fastapi import APIRouter, HTTPException

from app.model.assumptions import Scenario, SimulationRequest, SensitivityRequest
from app.model.sensitivity import run_sensitivity_analysis
from app.model.simulation import load_default_scenario, run_simulation

router = APIRouter()


@router.get("/scenario/default")
def get_default_scenario() -> dict:
    return load_default_scenario()


@router.post("/simulate")
def simulate(request: SimulationRequest) -> dict:
    try:
        scenario = Scenario.model_validate(request.scenario)
        return run_simulation(
            scenario=scenario,
            simulation_count=request.simulation_count,
            random_seed=request.random_seed,
            output_config=request.output,
            regime_filter=request.regime_filter,
        )
    except Exception as exc:  # pragma: no cover - surfaced through API
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sensitivity")
def sensitivity(request: SensitivityRequest) -> dict:
    try:
        scenario = Scenario.model_validate(request.scenario)
        return run_sensitivity_analysis(
            scenario=scenario,
            simulation_count=request.simulation_count,
            random_seed=request.random_seed,
            variables=request.variables,
        )
    except Exception as exc:  # pragma: no cover - surfaced through API
        raise HTTPException(status_code=400, detail=str(exc)) from exc
