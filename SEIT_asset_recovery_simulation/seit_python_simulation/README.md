# SEIT Python Monte Carlo Simulation

This is a runnable Python simulation for SEIT asset-sale / liquidation recovery.

## Install

```bash
pip install numpy pandas matplotlib
```

## Run

```bash
python seit_monte_carlo_simulation.py \
  --json seit_monte_carlo_inputs.json \
  --n-sims 100000 \
  --seed 42 \
  --output-dir seit_simulation_output
```

Override entry price as % of NAV:

```bash
python seit_monte_carlo_simulation.py \
  --json seit_monte_carlo_inputs.json \
  --entry-price-pct-nav 0.48 \
  --n-sims 100000
```

## Outputs

- `simulation_results.csv` — one row per simulation.
- `simulation_summary.csv` — percentiles and probability of positive / >20% / <-20% return.
- `asset_recovery_summary.csv` — simulated recovery/timing by asset bucket.
- `asset_inputs_used.csv` — cleaned input assumptions.
- `seit_total_return_histogram.png`
- `seit_gross_recovery_histogram.png`
- `seit_gross_recovery_vs_total_return.png`

## Core formula

```text
shareholder_recovery_pct_nav =
    weighted_gross_recovery * gross_assets_multiple_nav
    - debt_multiple_nav
    - wind_down_costs
    - tax_leakage
    - financing_drag
    + dividends_received

total_return =
    shareholder_recovery_pct_nav / entry_price_as_pct_nav - 1
```

These are stress-test assumptions, not forecasts.

## Recovery Ranges By Asset Bucket

The `Recovery distribution` field in `seit_monte_carlo_inputs.json` controls how each
asset bucket is sampled:

- `triangular`: use `Recovery low`, `Recovery mode`, and `Recovery high`
- `beta_pert`: smoother bounded distribution using `Recovery low`, `Recovery mode`, and `Recovery high`
- `uniform`: sample evenly between `Recovery low` and `Recovery high`
- `fixed`: always use `Recovery mode`

Examples:

- To model a bucket as a recovery range of `75%` to `90%`, set:
  - `Recovery distribution`: `uniform`
  - `Recovery low`: `0.75`
  - `Recovery mode`: `0.825` (kept for readability; not used by `uniform`)
  - `Recovery high`: `0.90`
- To model a bucket as `90%` to `105%`, set:
  - `Recovery distribution`: `uniform`
  - `Recovery low`: `0.90`
  - `Recovery mode`: `0.975`
  - `Recovery high`: `1.05`

That lets you treat each asset bucket as a direct recovery band instead of forcing
a single central case.

If you want smoother draws than `triangular` while still keeping a preferred central
case, use `beta_pert`. It stays within the same low/high bounds but concentrates
probability more naturally around the mode.
