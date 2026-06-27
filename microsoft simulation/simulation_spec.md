# Microsoft Probabilistic Valuation Model — Codex Build Spec

## 1. Objective

Build an interactive probabilistic valuation model for Microsoft (`MSFT`) that estimates the distribution of 10-year shareholder returns under uncertainty around:

* revenue growth by line of business
* AI revenue growth
* AI infrastructure capital intensity
* maintenance capex
* growth capex
* GPU economic life and depreciation shock risk
* margin compression from software-to-infrastructure mix shift
* terminal valuation multiple
* buyback capacity
* dividends
* probability of clearing a target CAGR hurdle

The model must not produce a single “fair value”. It must produce a probability distribution of future share prices and CAGRs.

Primary question:

```text
At today’s share price, what is the probability that MSFT returns at least X% CAGR over Y years?
```

Default target:

```text
target_cagr = 12%
horizon_years = 10
confidence_question = probability(total_return_cagr >= 12%)
```

The model should be deliberately coarse. Avoid false precision. The goal is to understand where Microsoft sits on the valuation spectrum given uncertain future economics.

---

## 2. Product shape

Build a local web app with:

```text
Python simulation backend
React + TypeScript frontend
JSON scenario configuration
Monte Carlo engine
Interactive charts
Editable assumptions
Scenario save/load
CSV export
```

Preferred stack:

```text
backend:
  Python 3.12
  FastAPI
  Pydantic
  NumPy
  Pandas
  SciPy optional
  pytest

frontend:
  Vite
  React
  TypeScript
  Tailwind
  Recharts
  Zustand or React context for state

dev:
  npm
  uv or poetry
  makefile
```

Keep simulation logic in pure Python so it can also be run from CLI or notebooks later.

---

## 3. Repository structure

```text
msft-valuation-model/
  README.md
  pyproject.toml
  package.json
  Makefile

  backend/
    app/
      main.py
      api/
        routes.py
      model/
        assumptions.py
        distributions.py
        simulation.py
        financials.py
        valuation.py
        sensitivity.py
      data/
        msft_default_scenario.json
      tests/
        test_distributions.py
        test_simulation_smoke.py
        test_financial_identities.py

  frontend/
    index.html
    src/
      main.tsx
      App.tsx
      api/client.ts
      state/useScenarioStore.ts
      components/
        Layout.tsx
        ScenarioEditor.tsx
        InputPanel.tsx
        DistributionChart.tsx
        CdfChart.tsx
        PercentileTable.tsx
        FanChart.tsx
        SensitivityChart.tsx
        ValuationSpectrum.tsx
        RevenueLineEditor.tsx
        CapexEditor.tsx
        ShockEditor.tsx
      types.ts

  docs/
    model_methodology.md
    assumptions_notes.md
```

---

## 4. Core modelling philosophy

The model should separate:

```text
revenue growth
→ operating margin
→ tax
→ NOPAT / net income
→ capex by type
→ depreciation by asset class
→ free cash flow
→ dividends
→ buybacks
→ share count
→ terminal EPS / FCF
→ terminal multiple
→ year-10 share price
→ total return CAGR
```

Do not hide capex inside a simple margin haircut. Capex must be modelled separately because:

1. cash flow is hit immediately
2. depreciation hits earnings gradually
3. AI infrastructure creates a new maintenance capex burden
4. buybacks are crowded out by capex
5. overbuild risk can cause a later utilisation / pricing / depreciation shock

---

## 5. Simulation output

Each run should produce:

```text
simulation_count
target_cagr
probability_above_target
probability_of_loss
median_cagr
mean_cagr
p10_cagr
p25_cagr
p50_cagr
p75_cagr
p90_cagr
p95_cagr
p10_terminal_share_price
p25_terminal_share_price
p50_terminal_share_price
p75_terminal_share_price
p90_terminal_share_price
p95_terminal_share_price
median_year_10_revenue
median_year_10_eps
median_year_10_fcf_per_share
median_terminal_pe
median_terminal_fcf_multiple
median_total_capex_to_revenue
median_maintenance_capex_to_revenue
median_growth_capex_to_revenue
```

Also return per-year percentile paths for:

```text
revenue
operating_income
net_income
eps
fcf
capex
maintenance_capex
growth_capex
share_count
gross_margin
operating_margin
```

---

## 6. Required frontend views

### 6.1 Overview dashboard

Show:

* current share price
* current EPS
* current PE
* target CAGR
* simulation count
* median CAGR
* probability above target CAGR
* probability of negative total return
* p10 / p50 / p90 year-10 share price
* valuation zone label

Example valuation zone labels:

```text
Deep value
Attractive
Fair / watchlist
Expensive
Heroic
```

These labels should be computed from expected return distribution, not current PE alone.

Suggested rules:

```text
if P(total_return_cagr >= target) >= 0.85:
    zone = "Attractive / high confidence"
elif P(total_return_cagr >= target) >= 0.60:
    zone = "Interesting"
elif P(total_return_cagr >= target) >= 0.35:
    zone = "Watchlist / fair"
elif P(total_return_cagr >= target) >= 0.15:
    zone = "Demanding"
else:
    zone = "Heroic / low odds"
```

### 6.2 Distribution chart

Histogram of simulated 10-year CAGRs.

Vertical markers:

```text
0%
target CAGR
median CAGR
```

### 6.3 CDF chart

Cumulative probability curve for 10-year CAGR.

User should be able to read:

```text
P(CAGR > 8%)
P(CAGR > 10%)
P(CAGR > 12%)
P(CAGR > 15%)
```

### 6.4 Percentile table

Rows:

```text
P5
P10
P25
P50
P75
P90
P95
```

Columns:

```text
terminal share price
total return multiple
10-year CAGR
year-10 EPS
terminal PE
year-10 FCF/share
terminal FCF multiple
```

### 6.5 Fan chart

Annual percentile paths for:

* revenue
* EPS
* FCF/share
* share price implied by terminal methodology rolled forward
* capex/revenue
* maintenance capex/revenue

### 6.6 Revenue-line editor

Editable revenue lines:

```text
Core Productivity
AI Apps / Copilot
Azure non-AI cloud
Azure AI / infrastructure
More Personal Computing
```

For each revenue line expose:

```text
starting_revenue
growth_years_1_to_3_min
growth_years_1_to_3_mode
growth_years_1_to_3_max

growth_years_4_to_7_min
growth_years_4_to_7_mode
growth_years_4_to_7_max

growth_years_8_to_10_min
growth_years_8_to_10_mode
growth_years_8_to_10_max

starting_gross_margin
terminal_gross_margin_min
terminal_gross_margin_mode
terminal_gross_margin_max

capex_intensity_min
capex_intensity_mode
capex_intensity_max
```

### 6.7 Capex editor

Expose:

```text
short_lived_capex_share
long_lived_capex_share
gpu_economic_life_min/mode/max
datacenter_life_min/mode/max
maintenance_capex_floor
component_cost_deflation_min/mode/max
component_cost_inflation_min/mode/max
```

### 6.8 Shock editor

Expose shock settings:

```text
enable_price_crash
shock_probability
shock_year_min
shock_year_mode
shock_year_max

ai_price_crash_min
ai_price_crash_mode
ai_price_crash_max

utilisation_decline_min
utilisation_decline_mode
utilisation_decline_max

accelerated_depreciation_probability
accelerated_depreciation_pct_min
accelerated_depreciation_pct_mode
accelerated_depreciation_pct_max

post_shock_growth_capex_reduction_min
post_shock_growth_capex_reduction_mode
post_shock_growth_capex_reduction_max
```

Shock behaviour:

```text
If shock occurs:
  - reduce AI revenue growth after shock year
  - reduce AI gross margin
  - reduce utilisation
  - reduce future GPU purchase cost / maintenance cost
  - reduce growth capex
  - optionally apply a one-off accelerated depreciation charge
  - reduce terminal multiple
```

### 6.9 Sensitivity / tornado chart

Run a simple sensitivity analysis by shocking each major input up/down while holding others constant.

Show variables ranked by impact on median CAGR:

```text
terminal PE
AI revenue growth
Azure non-AI growth
GPU economic life
AI gross margin
capex intensity
operating margin
share count reduction
shock probability
```

---

## 7. Distribution functions

Implement Beta-PERT distribution as the default.

### 7.1 Beta-PERT

Inputs:

```text
min
mode
max
lambda = 4
```

Function:

```python
def sample_pert(min_value: float, mode_value: float, max_value: float, size: int, lamb: float = 4.0) -> np.ndarray:
    ...
```

Use Beta distribution transformation:

```text
alpha = 1 + lambda * (mode - min) / (max - min)
beta = 1 + lambda * (max - mode) / (max - min)
sample = min + beta_sample * (max - min)
```

Handle degenerate cases where min == max.

Also support:

```text
fixed
normal_clamped
lognormal
triangular
```

But MVP can use PERT and fixed only.

---

## 8. Seed assumptions

Create this file:

```text
backend/app/data/msft_default_scenario.json
```

Use the following default contents.

```json
{
  "meta": {
    "ticker": "MSFT",
    "company": "Microsoft Corporation",
    "currency": "USD",
    "as_of_date": "2026-06-27",
    "description": "Default rough-prior scenario for probabilistic 10-year MSFT valuation with AI capex cycle."
  },
  "market": {
    "current_share_price": 372.97,
    "current_market_cap_bn": 2776.8,
    "current_eps_ttm": 16.8,
    "current_pe_ttm": 22.2,
    "estimated_diluted_shares_bn": 7.44
  },
  "base_financials": {
    "fy2025_revenue_bn": 281.7,
    "fy2025_operating_income_bn": 128.5,
    "fy2025_net_income_bn": 101.8,
    "fy2025_eps": 13.64,
    "fy2025_ppe_additions_bn": 64.6,
    "fy2025_depreciation_bn": 22.0,
    "fy2025_cloud_gross_margin_pct": 69.0,
    "fy2026_q3_revenue_bn": 82.9,
    "fy2026_q3_eps": 4.27,
    "fy2026_q3_capex_bn": 31.9,
    "fy2026_q3_cash_paid_for_ppe_bn": 30.9,
    "fy2026_q3_fcf_bn": 15.8,
    "fy2026_q3_cloud_revenue_bn": 54.5,
    "fy2026_q3_cloud_gross_margin_pct": 66.0,
    "fy2026_q3_ai_arr_bn": 37.0,
    "calendar_2026_capex_guidance_bn": 190.0
  },
  "simulation": {
    "horizon_years": 10,
    "simulation_count": 20000,
    "random_seed": 42,
    "target_cagr": 0.12,
    "tax_rate": {
      "type": "pert",
      "min": 0.17,
      "mode": 0.19,
      "max": 0.21
    }
  },
  "revenue_lines": [
    {
      "name": "Core Productivity",
      "starting_revenue_bn": 128.0,
      "description": "Core Microsoft 365, Office, LinkedIn, Dynamics, security and related productivity stack excluding explicit AI uplift.",
      "growth": {
        "years_1_to_3": { "type": "pert", "min": 0.06, "mode": 0.09, "max": 0.13 },
        "years_4_to_7": { "type": "pert", "min": 0.04, "mode": 0.07, "max": 0.10 },
        "years_8_to_10": { "type": "pert", "min": 0.03, "mode": 0.05, "max": 0.08 }
      },
      "gross_margin": {
        "start": 0.80,
        "terminal": { "type": "pert", "min": 0.74, "mode": 0.78, "max": 0.82 }
      },
      "capex_intensity": {
        "maintenance_pct_of_revenue": { "type": "pert", "min": 0.02, "mode": 0.03, "max": 0.05 },
        "growth_pct_of_incremental_revenue": { "type": "pert", "min": 0.05, "mode": 0.08, "max": 0.12 }
      }
    },
    {
      "name": "AI Apps / Copilot",
      "starting_revenue_bn": 12.0,
      "description": "Copilot, GitHub Copilot, Security Copilot, Dynamics agents, LinkedIn agentic products and other first-party AI application revenue.",
      "growth": {
        "years_1_to_3": { "type": "pert", "min": 0.20, "mode": 0.35, "max": 0.60 },
        "years_4_to_7": { "type": "pert", "min": 0.08, "mode": 0.18, "max": 0.35 },
        "years_8_to_10": { "type": "pert", "min": 0.03, "mode": 0.10, "max": 0.20 }
      },
      "gross_margin": {
        "start": 0.55,
        "terminal": { "type": "pert", "min": 0.45, "mode": 0.60, "max": 0.72 }
      },
      "capex_intensity": {
        "maintenance_pct_of_revenue": { "type": "pert", "min": 0.08, "mode": 0.15, "max": 0.30 },
        "growth_pct_of_incremental_revenue": { "type": "pert", "min": 0.40, "mode": 0.80, "max": 1.40 }
      }
    },
    {
      "name": "Azure non-AI cloud",
      "starting_revenue_bn": 115.0,
      "description": "Azure and cloud platform revenue excluding explicit AI infrastructure usage.",
      "growth": {
        "years_1_to_3": { "type": "pert", "min": 0.12, "mode": 0.18, "max": 0.25 },
        "years_4_to_7": { "type": "pert", "min": 0.07, "mode": 0.12, "max": 0.18 },
        "years_8_to_10": { "type": "pert", "min": 0.04, "mode": 0.08, "max": 0.12 }
      },
      "gross_margin": {
        "start": 0.66,
        "terminal": { "type": "pert", "min": 0.58, "mode": 0.64, "max": 0.70 }
      },
      "capex_intensity": {
        "maintenance_pct_of_revenue": { "type": "pert", "min": 0.14, "mode": 0.20, "max": 0.28 },
        "growth_pct_of_incremental_revenue": { "type": "pert", "min": 0.60, "mode": 0.90, "max": 1.25 }
      }
    },
    {
      "name": "Azure AI / infrastructure",
      "starting_revenue_bn": 25.0,
      "description": "AI infrastructure, training, inference, OpenAI-related cloud consumption, Foundry, model hosting and AI usage-based cloud services.",
      "growth": {
        "years_1_to_3": { "type": "pert", "min": 0.25, "mode": 0.50, "max": 0.90 },
        "years_4_to_7": { "type": "pert", "min": 0.05, "mode": 0.22, "max": 0.45 },
        "years_8_to_10": { "type": "pert", "min": -0.02, "mode": 0.08, "max": 0.22 }
      },
      "gross_margin": {
        "start": 0.45,
        "terminal": { "type": "pert", "min": 0.25, "mode": 0.45, "max": 0.62 }
      },
      "capex_intensity": {
        "maintenance_pct_of_revenue": { "type": "pert", "min": 0.20, "mode": 0.35, "max": 0.60 },
        "growth_pct_of_incremental_revenue": { "type": "pert", "min": 1.00, "mode": 1.80, "max": 3.00 }
      }
    },
    {
      "name": "More Personal Computing",
      "starting_revenue_bn": 53.0,
      "description": "Windows OEM, devices, gaming, search advertising and consumer computing.",
      "growth": {
        "years_1_to_3": { "type": "pert", "min": -0.03, "mode": 0.02, "max": 0.07 },
        "years_4_to_7": { "type": "pert", "min": -0.02, "mode": 0.02, "max": 0.06 },
        "years_8_to_10": { "type": "pert", "min": -0.02, "mode": 0.01, "max": 0.05 }
      },
      "gross_margin": {
        "start": 0.54,
        "terminal": { "type": "pert", "min": 0.48, "mode": 0.54, "max": 0.60 }
      },
      "capex_intensity": {
        "maintenance_pct_of_revenue": { "type": "pert", "min": 0.02, "mode": 0.04, "max": 0.08 },
        "growth_pct_of_incremental_revenue": { "type": "pert", "min": 0.05, "mode": 0.10, "max": 0.20 }
      }
    }
  ],
  "opex": {
    "rd_and_sga_pct_of_revenue": {
      "start": 0.22,
      "terminal": { "type": "pert", "min": 0.19, "mode": 0.21, "max": 0.24 }
    },
    "ai_extra_opex_pct_of_ai_revenue": {
      "type": "pert",
      "min": 0.03,
      "mode": 0.06,
      "max": 0.12
    }
  },
  "capex": {
    "short_lived_asset_share": {
      "type": "pert",
      "min": 0.55,
      "mode": 0.67,
      "max": 0.75
    },
    "long_lived_asset_share": {
      "type": "derived",
      "formula": "1 - short_lived_asset_share"
    },
    "gpu_economic_life_years": {
      "type": "pert",
      "min": 2.0,
      "mode": 3.0,
      "max": 4.5
    },
    "datacenter_economic_life_years": {
      "type": "pert",
      "min": 10.0,
      "mode": 15.0,
      "max": 20.0
    },
    "component_cost_change_per_year": {
      "description": "Negative means cheaper future capacity; positive means continued component inflation.",
      "type": "pert",
      "min": -0.12,
      "mode": -0.04,
      "max": 0.05
    },
    "initial_capex_overlay_bn": {
      "description": "For FY2026/FY2027 elevated capex buildout not fully implied by incremental revenue formula.",
      "year_1": { "type": "pert", "min": 160.0, "mode": 190.0, "max": 220.0 },
      "year_2": { "type": "pert", "min": 130.0, "mode": 170.0, "max": 220.0 },
      "year_3": { "type": "pert", "min": 100.0, "mode": 140.0, "max": 200.0 }
    }
  },
  "shock": {
    "enable_price_crash": true,
    "shock_probability": {
      "type": "pert",
      "min": 0.15,
      "mode": 0.30,
      "max": 0.50
    },
    "shock_year": {
      "type": "pert_integer",
      "min": 3,
      "mode": 5,
      "max": 7
    },
    "ai_price_decline": {
      "description": "One-off effective pricing reset for AI compute/services.",
      "type": "pert",
      "min": 0.15,
      "mode": 0.35,
      "max": 0.60
    },
    "utilisation_decline": {
      "type": "pert",
      "min": 0.05,
      "mode": 0.18,
      "max": 0.35
    },
    "ai_growth_haircut_after_shock": {
      "type": "pert",
      "min": 0.20,
      "mode": 0.40,
      "max": 0.70
    },
    "ai_margin_haircut_after_shock": {
      "type": "pert",
      "min": 0.05,
      "mode": 0.12,
      "max": 0.25
    },
    "future_growth_capex_reduction_after_shock": {
      "type": "pert",
      "min": 0.15,
      "mode": 0.35,
      "max": 0.60
    },
    "accelerated_depreciation_probability_given_shock": {
      "type": "pert",
      "min": 0.10,
      "mode": 0.25,
      "max": 0.50
    },
    "accelerated_depreciation_pct_of_short_lived_asset_base": {
      "type": "pert",
      "min": 0.05,
      "mode": 0.15,
      "max": 0.35
    },
    "terminal_multiple_haircut_given_shock": {
      "type": "pert",
      "min": 0.05,
      "mode": 0.15,
      "max": 0.30
    }
  },
  "capital_return": {
    "dividend_payout_ratio": {
      "type": "pert",
      "min": 0.18,
      "mode": 0.22,
      "max": 0.28
    },
    "buyback_pct_of_post_dividend_fcf": {
      "type": "pert",
      "min": 0.20,
      "mode": 0.45,
      "max": 0.75
    },
    "buyback_price_premium_to_intrinsic": {
      "description": "Penalty for buybacks occurring at above-modelled fair value.",
      "type": "pert",
      "min": -0.05,
      "mode": 0.05,
      "max": 0.20
    },
    "minimum_cash_buffer_bn": 80.0
  },
  "valuation": {
    "terminal_pe": {
      "type": "pert",
      "min": 15.0,
      "mode": 21.0,
      "max": 28.0
    },
    "terminal_fcf_multiple": {
      "type": "pert",
      "min": 14.0,
      "mode": 20.0,
      "max": 27.0
    },
    "valuation_weight_eps": 0.70,
    "valuation_weight_fcf": 0.30,
    "net_cash_adjustment_bn": 0.0
  }
}
```

Notes on seed assumptions:

* Starting revenue lines are approximate and intentionally rough.
* AI Apps and Azure AI are separated for modelling purposes even though Microsoft does not fully disclose them this way.
* The AI revenue lines roughly reconcile to Microsoft’s disclosed AI annual run-rate.
* The model should allow the user to edit every seed assumption in the UI.

---

## 9. Financial model details

### 9.1 Revenue

For each simulation and each revenue line:

```python
revenue[line, year] = revenue[line, year - 1] * (1 + sampled_growth_rate[line, period])
```

Use growth periods:

```text
years 1–3
years 4–7
years 8–10
```

Optionally sample one CAGR per period per simulation, not a new independent growth rate every year. This prevents unrealistic noise.

### 9.2 Gross margin

For each revenue line, interpolate from starting gross margin to sampled terminal gross margin:

```python
gross_margin[line, year] = linear_interpolate(start_margin, terminal_margin, year / horizon)
gross_profit[line, year] = revenue[line, year] * gross_margin[line, year]
```

If a shock occurs, apply margin haircut to AI revenue lines from shock year onward.

### 9.3 Opex

Simplified:

```python
opex = total_revenue * rd_and_sga_pct_of_revenue
opex += ai_revenue * ai_extra_opex_pct_of_ai_revenue
```

Operating income:

```python
operating_income = total_gross_profit - opex
```

### 9.4 Tax and net income

```python
tax = max(0, operating_income * tax_rate)
net_income_before_depreciation_shock = operating_income - tax
```

If accelerated depreciation shock occurs:

```python
depreciation_shock = short_lived_asset_base * accelerated_depreciation_pct
tax_adjusted_depreciation_shock = depreciation_shock * (1 - tax_rate)
net_income = net_income_before_depreciation_shock - tax_adjusted_depreciation_shock
```

For EPS, use net income after depreciation shock.

### 9.5 Capex

Compute two capex layers:

```text
maintenance capex
growth capex
```

Maintenance capex:

```python
maintenance_capex[line, year] = revenue[line, year] * sampled_maintenance_capex_pct[line]
```

For AI infrastructure, also calculate asset-base maintenance:

```python
short_lived_replacement_capex = short_lived_asset_base / gpu_economic_life_years
long_lived_replacement_capex = long_lived_asset_base / datacenter_economic_life_years
```

Use the larger of:

```python
revenue_based_maintenance_capex
asset_base_replacement_capex
```

Growth capex:

```python
incremental_revenue = max(0, revenue[line, year] - revenue[line, year - 1])
growth_capex[line, year] = incremental_revenue * growth_pct_of_incremental_revenue[line]
```

Initial capex overlay:

```python
total_capex[year] = max(
    calculated_maintenance_capex + calculated_growth_capex,
    initial_capex_overlay_bn[year] if year in [1,2,3] else 0
)
```

Allocate total capex into:

```python
short_lived_capex = total_capex * short_lived_asset_share
long_lived_capex = total_capex * long_lived_asset_share
```

Asset bases:

```python
short_lived_asset_base[year] = short_lived_asset_base[year-1] + short_lived_capex - short_lived_depreciation
long_lived_asset_base[year] = long_lived_asset_base[year-1] + long_lived_capex - long_lived_depreciation
```

Depreciation:

```python
short_lived_depreciation = short_lived_asset_base_beginning / gpu_economic_life_years
long_lived_depreciation = long_lived_asset_base_beginning / datacenter_economic_life_years
```

For MVP, depreciation can be used as a diagnostic rather than fully integrated into operating income, since gross margin and opex assumptions already partly capture depreciation. But expose both:

```text
reported-style EPS
owner-earnings FCF
```

Preferred output metric:

```text
owner earnings = net income + depreciation - maintenance capex
free cash flow = operating_cash_flow_proxy - total_capex
```

Simplified operating cash flow proxy:

```python
operating_cash_flow = net_income + depreciation
fcf = operating_cash_flow - total_capex
```

### 9.6 Shock behaviour

For each simulation:

```python
shock_occurs = random_uniform < sampled_shock_probability
```

If shock occurs:

```python
shock_year = sample integer from PERT
```

From shock year onward:

```python
AI revenue growth *= (1 - ai_growth_haircut_after_shock)
AI gross margin -= ai_margin_haircut_after_shock
future growth capex *= (1 - future_growth_capex_reduction_after_shock)
component cost change becomes more negative
terminal PE *= (1 - terminal_multiple_haircut_given_shock)
terminal FCF multiple *= (1 - terminal_multiple_haircut_given_shock)
```

Also:

```python
accelerated_depreciation_occurs = random_uniform < sampled_accelerated_depreciation_probability_given_shock
```

If accelerated depreciation occurs:

```python
one_off_charge = short_lived_asset_base * accelerated_depreciation_pct
net_income -= one_off_charge * (1 - tax_rate)
```

This should hit EPS in that year and reduce asset base.

### 9.7 Dividends

```python
dividends_paid = max(0, net_income * dividend_payout_ratio)
dividend_per_share = dividends_paid / share_count
cumulative_dividends_per_share += dividend_per_share
```

### 9.8 Buybacks

Available buyback cash:

```python
buyback_cash = max(0, fcf - dividends_paid)
buyback_cash *= buyback_pct_of_post_dividend_fcf
```

Approximate buyback price each year:

```python
estimated_share_price = prior_year_eps * rolling_pe_estimate
buyback_price = estimated_share_price * (1 + buyback_price_premium_to_intrinsic)
shares_reduced = buyback_cash / buyback_price
share_count = max(share_count - shares_reduced, share_count * 0.95)
```

The `share_count * 0.95` guard prevents unrealistic >5% annual share count reduction.

### 9.9 Terminal valuation

At year 10:

```python
terminal_value_eps = year_10_eps * terminal_pe
terminal_value_fcf = year_10_fcf_per_share * terminal_fcf_multiple

terminal_share_price =
    valuation_weight_eps * terminal_value_eps
  + valuation_weight_fcf * terminal_value_fcf
  + net_cash_adjustment_per_share
```

Total ending value:

```python
ending_value = terminal_share_price + cumulative_dividends_per_share
```

Total return CAGR:

```python
cagr = (ending_value / current_share_price) ** (1 / horizon_years) - 1
```

---

## 10. API design

### 10.1 `GET /api/scenario/default`

Returns default scenario JSON.

### 10.2 `POST /api/simulate`

Request:

```json
{
  "scenario": {},
  "simulation_count": 20000,
  "random_seed": 42
}
```

Response:

```json
{
  "summary": {
    "target_cagr": 0.12,
    "probability_above_target": 0.0,
    "probability_of_loss": 0.0,
    "mean_cagr": 0.0,
    "median_cagr": 0.0,
    "p10_cagr": 0.0,
    "p25_cagr": 0.0,
    "p50_cagr": 0.0,
    "p75_cagr": 0.0,
    "p90_cagr": 0.0
  },
  "percentiles": [
    {
      "percentile": 10,
      "terminal_share_price": 0.0,
      "cagr": 0.0,
      "terminal_eps": 0.0,
      "terminal_pe": 0.0,
      "terminal_fcf_per_share": 0.0
    }
  ],
  "histogram": [
    {
      "bin_start": 0.0,
      "bin_end": 0.0,
      "count": 0
    }
  ],
  "cdf": [
    {
      "cagr": 0.0,
      "probability_less_than_or_equal": 0.0
    }
  ],
  "fan_chart": [
    {
      "year": 1,
      "metric": "eps",
      "p10": 0.0,
      "p25": 0.0,
      "p50": 0.0,
      "p75": 0.0,
      "p90": 0.0
    }
  ],
  "diagnostics": {
    "median_year_10_revenue_bn": 0.0,
    "median_year_10_eps": 0.0,
    "median_year_10_fcf_per_share": 0.0,
    "median_capex_to_revenue": 0.0,
    "median_maintenance_capex_to_revenue": 0.0,
    "median_growth_capex_to_revenue": 0.0,
    "shock_frequency_realised": 0.0,
    "accelerated_depreciation_frequency_realised": 0.0
  }
}
```

### 10.3 `POST /api/sensitivity`

Run sensitivity analysis.

Request:

```json
{
  "scenario": {},
  "simulation_count": 5000,
  "variables": [
    "terminal_pe",
    "ai_revenue_growth",
    "gpu_economic_life",
    "shock_probability",
    "capex_intensity"
  ]
}
```

Response:

```json
{
  "items": [
    {
      "variable": "terminal_pe",
      "low_case_median_cagr": 0.0,
      "base_case_median_cagr": 0.0,
      "high_case_median_cagr": 0.0,
      "impact": 0.0
    }
  ]
}
```

---

## 11. CLI

Add CLI entry point:

```bash
python -m backend.app.model.simulation --scenario backend/app/data/msft_default_scenario.json --runs 20000 --seed 42
```

Output summary JSON to stdout.

Also support:

```bash
python -m backend.app.model.simulation --scenario scenario.json --output results.csv
```

---

## 12. Tests

Create tests for:

### 12.1 Distribution tests

* PERT samples stay between min and max
* sample mean is close to expected rough direction
* fixed distributions return constant value
* integer PERT returns integers in range

### 12.2 Financial identity tests

* revenue equals sum of revenue lines
* gross profit equals sum of revenue × gross margin
* FCF equals operating cash flow proxy minus capex
* EPS equals net income / share count
* terminal value calculation is stable
* CAGRs are correctly calculated

### 12.3 Smoke tests

* default scenario runs 1,000 simulations without errors
* no NaN values in output
* no negative share count
* no impossible negative terminal multiples
* no impossible revenue below zero

---

## 13. UI requirements

The app should feel like a valuation cockpit.

### Required controls

Top-level controls:

```text
current share price
target CAGR
horizon years
simulation count
random seed
valuation method weights
```

Revenue controls:

```text
starting revenue by line
growth min/mode/max by period
terminal gross margin min/mode/max
capex intensity min/mode/max
```

Capex controls:

```text
short-lived asset share
GPU economic life
datacenter economic life
component cost change
initial capex overlay years 1–3
```

Shock controls:

```text
shock probability
shock year
AI price decline
utilisation decline
AI growth haircut
AI margin haircut
depreciation shock probability
depreciation shock size
terminal multiple haircut
```

Valuation controls:

```text
terminal PE min/mode/max
terminal FCF multiple min/mode/max
EPS/FCF valuation weights
dividend payout
buyback share of post-dividend FCF
```

### Required charts

Use Recharts:

```text
Histogram: CAGR distribution
Line chart: CDF of CAGR
Fan chart: EPS path
Fan chart: FCF/share path
Fan chart: capex/revenue path
Stacked area or line chart: revenue by line, median path
Tornado chart: sensitivity
Percentile table
```

---

## 14. Implementation sequence for Codex

Build in this order:

### Phase 1 — backend model

1. Create Python project.
2. Define Pydantic models for scenario schema.
3. Implement PERT distribution sampler.
4. Implement revenue projection.
5. Implement gross margin and opex.
6. Implement capex, depreciation, FCF.
7. Implement shock logic.
8. Implement dividends and buybacks.
9. Implement terminal valuation.
10. Implement simulation summary and percentiles.
11. Add smoke tests.

### Phase 2 — FastAPI

1. Add `/api/scenario/default`.
2. Add `/api/simulate`.
3. Add `/api/sensitivity`.
4. Add CORS for local frontend.
5. Add error handling for invalid scenarios.

### Phase 3 — frontend

1. Create Vite React app.
2. Load default scenario.
3. Build editable scenario state.
4. Build input panels.
5. Call simulation API.
6. Render dashboard.
7. Render histogram, CDF, fan charts and percentile table.
8. Add save/load scenario JSON.
9. Add export results CSV.

### Phase 4 — polish

1. Add loading state.
2. Add validation warnings.
3. Add preset buttons:

   * conservative
   * base
   * bullish
   * capex crash
   * AI abundance / price compression
4. Add methodology notes.
5. Add README run instructions.

---

## 15. Preset scenarios

Create scenario presets derived from the default.

### 15.1 Conservative

Changes:

```text
lower AI growth
higher capex intensity
higher shock probability
lower terminal PE
shorter GPU economic life
lower terminal gross margin
```

### 15.2 Base

Use default.

### 15.3 Bullish

Changes:

```text
higher Azure AI growth
AI margins stabilise
capex intensity falls after year 5
GPU life closer to 4 years
terminal PE centred around 24–26x
lower shock probability
```

### 15.4 AI abundance / price crash

Changes:

```text
shock probability high
shock year centred around year 4
AI price decline 40–60%
terminal multiple haircut 20–30%
accelerated depreciation likely
future capex falls but gross margin and utilisation fall too
```

### 15.5 Capex overshoot

Changes:

```text
years 1–4 capex very high
growth slows years 5–10
maintenance capex remains high
buybacks heavily suppressed
terminal PE compressed
```

---

## 16. README instructions

README should include:

```bash
# backend
cd backend
uv sync
uv run fastapi dev app/main.py

# frontend
cd frontend
npm install
npm run dev
```

Also include:

```bash
# run backend tests
uv run pytest

# run simulation from CLI
uv run python -m app.model.simulation --scenario app/data/msft_default_scenario.json --runs 20000 --seed 42
```

---

## 17. Important modelling caveats to show in UI

Display this caveat in the app:

```text
This model is not a forecast. It is a probabilistic valuation framework. The output depends entirely on the chosen priors. The purpose is to understand what must be true for MSFT to clear a target return hurdle, and how sensitive that result is to AI growth, capex intensity, GPU life, margin compression, buybacks and terminal valuation.
```

Also show:

```text
Do not rely on EPS alone. Compare EPS CAGR with FCF/share CAGR. If EPS rises while FCF conversion deteriorates, the model may be overstating owner returns.
```

---

## 18. Acceptance criteria

The build is complete when:

1. The app starts locally with one backend command and one frontend command.
2. Default scenario loads automatically.
3. User can edit assumptions in the UI.
4. User can run 20,000 simulations in under 5 seconds on a normal laptop.
5. Dashboard shows probability of clearing target CAGR.
6. Histogram and CDF render correctly.
7. Percentile table renders correctly.
8. Fan charts render correctly.
9. Sensitivity chart ranks major variables by impact.
10. User can save edited scenario to JSON.
11. User can reload scenario JSON.
12. Backend tests pass.
13. No simulation output contains NaN, infinite values or negative share count.
14. README explains model and run instructions.
