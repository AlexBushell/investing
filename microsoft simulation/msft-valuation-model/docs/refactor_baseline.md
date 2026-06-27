# Refactor Baseline

Baseline captured before starting the generic probabilistic valuation platform refactor.

Date: 2026-06-27

## Current Scope

The current application is a Microsoft-specific probabilistic valuation cockpit with:

- Python/FastAPI simulation backend.
- React/Vite frontend.
- Editable MSFT market, valuation, capital return, output, and revenue-line priors.
- Probability histogram with cumulative-confidence overlay and 85% confidence floor.
- Regime diagnostics and conditional regime filtering.
- Scenario JSON save/load.

## Verification Commands

Backend:

```powershell
cd "C:\dev\investing\microsoft simulation\msft-valuation-model\backend"
.\.venv\Scripts\python.exe -m pytest
```

Frontend:

```powershell
cd "C:\dev\investing\microsoft simulation\msft-valuation-model\frontend"
npm run build
```

Expected current result:

- Backend tests pass.
- Frontend TypeScript and Vite build pass.
- Vite may warn that the main JS chunk is larger than 500 kB.
- FastAPI/Starlette may warn that `httpx` use in `TestClient` is deprecated by that dependency stack.
- Pytest may warn that it cannot create `.pytest_cache` in the sandboxed environment.

## Workspace Note

The Git repository root is `C:\dev\investing`, not `msft-valuation-model`. From the app directory, `git status --short` currently reports the app parent as untracked plus an unrelated tracked CSV change outside this project. Before a large refactor, either add this app folder to the parent repo deliberately or create a dedicated repo boundary for the valuation model.
