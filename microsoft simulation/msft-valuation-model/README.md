# MSFT Valuation Model

Probabilistic Microsoft valuation cockpit with a Python simulation backend and a React frontend.

The build follows the amended spec:

- the combined probability distribution chart replaces separate histogram and CDF views
- backend simulation is the first delivery slice
- assumptions are intentionally coarse and editable

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m uvicorn app.main:app --reload
```

## Tests

```bash
cd backend
.venv\Scripts\python -m pytest
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the API at `http://127.0.0.1:8000/api` unless `VITE_API_BASE_URL` is set.

## CLI

```bash
cd backend
.venv\Scripts\python -m app.model.simulation --scenario app/data/msft_default_scenario.json --runs 20000 --seed 42
```

## Current Model Notes

`Run fresh draw` uses the current scenario assumptions but generates a new random seed, so the output can move slightly from run to run. `Replay scenario seed` uses the scenario seed, currently `42` in the default JSON, so it is useful for comparing assumption edits against a stable draw.

The Regime Mix panel shows how the Monte Carlo paths were classified into latent AI/capex world states. Selecting a regime filters the displayed return distribution to that subset of paths while preserving the full-run regime frequencies for context.

Current regimes:

- `AI scarcity / high ROI`: strong AI demand, better margins, and supportive terminal valuation.
- `Balanced growth`: more normal demand, capex, and valuation outcomes.
- `Overbuild / price compression`: heavy buildout, weaker utilization, and valuation pressure.
- `AI disappointment`: slower AI monetization with weaker growth and margin support.

Scenario JSON can be saved and reloaded from the editor. Loading or reloading a scenario clears the prior result and immediately reruns the loaded scenario so the visible charts match the active inputs.

## Caveat

This model is not a forecast. It is a probabilistic valuation framework. The output depends entirely on the chosen priors.
