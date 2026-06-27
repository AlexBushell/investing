# Adaptation Spec — Convert Microsoft Valuation Model into Generic Probabilistic Stock Valuation Platform

## 1. Objective

Refactor the current Microsoft-specific probabilistic valuation model into a reusable valuation platform that supports multiple business model types.

The target state is:

```text
Generic Monte Carlo valuation engine
+ pluggable operating model modules
+ common output schema
+ common distribution / hurdle-rate visualisation
+ company-specific default priors
```

The platform must continue to support the existing Microsoft AI/cloud capex model, but it should also support additional stocks such as:

```text
Persimmon Homes / PSN.L
Gateley Holdings / GTLY.L
Generic companies with revenue/margin/FCF assumptions
```

The model should answer the same core investment question for every company:

```text
At today’s share price, what is the probability that this stock clears a target total-return CAGR over the chosen horizon?
```

Default hurdle:

```text
Target CAGR: 12%
Horizon: 10 years
Simulation count: 20,000
Histogram buckets: 20
```

---

## 2. Current problem

The existing Microsoft model mixes three concerns:

```text
1. Monte Carlo simulation mechanics
2. Generic financial valuation logic
3. Microsoft-specific AI/cloud operating assumptions
```

This makes the model hard to adapt to companies whose economics are driven by different variables.

Examples:

```text
Microsoft:
  Azure growth, AI capex, GPU life, cloud gross margin, Copilot monetisation

Persimmon:
  completions, average selling price, build cost, land cost, sales rate, mortgage affordability

Gateley:
  fee earners, utilisation, billing rates, staff cost ratio, working capital, acquisitions
```

The refactor must separate:

```text
valuation_engine = generic
business_model = pluggable
company_priors = scenario-specific
frontend = schema-driven where possible
```

---

## 3. Target architecture

### 3.1 Backend package structure

Refactor backend to:

```text
backend/
  app/
    main.py

    api/
      routes.py

    core/
      distributions.py
      simulation_runner.py
      output_distribution.py
      sensitivity.py
      validation.py

    valuation/
      terminal_value.py
      capital_returns.py
      valuation_summary.py
      valuation_zones.py

    business_models/
      __init__.py
      registry.py
      base.py
      generic_revenue_margin_fcf.py
      cloud_software_ai_infrastructure.py
      housebuilder.py
      professional_services.py

    schemas/
      common.py
      distributions.py
      scenario.py
      outputs.py
      business_model_inputs.py

    data/
      scenarios/
        msft_cloud_ai_default.json
        psn_housebuilder_default.json
        gtly_professional_services_default.json
        generic_default.json

      presets/
        cloud_ai/
          base.json
          conservative.json
          ai_abundance_price_crash.json
          capex_overshoot.json

        housebuilder/
          base.json
          housing_downturn.json
          volume_recovery.json

        professional_services/
          base.json
          transactional_downturn.json
          acquisition_rollup.json

    tests/
      test_distributions.py
      test_distribution_buckets.py
      test_business_model_registry.py
      test_generic_model_smoke.py
      test_cloud_ai_model_smoke.py
      test_housebuilder_model_smoke.py
      test_professional_services_model_smoke.py
      test_common_outputs.py
      test_valuation_summary.py
```

### 3.2 Frontend structure

Refactor frontend to:

```text
frontend/
  src/
    App.tsx

    api/
      client.ts

    model/
      scenarioTypes.ts
      outputTypes.ts
      businessModelTypes.ts

    state/
      useScenarioStore.ts

    components/
      Layout.tsx
      CompanySelector.tsx
      ScenarioHeader.tsx
      ValuationDashboard.tsx
      ProbabilityHistogramWithConfidenceOverlay.tsx
      PercentileTable.tsx
      FanChart.tsx
      SensitivityChart.tsx
      ScenarioJsonEditor.tsx

      editors/
        CommonMarketInputsEditor.tsx
        CommonValuationInputsEditor.tsx
        CapitalReturnEditor.tsx
        DistributionSettingsEditor.tsx

        GenericRevenueMarginFcfEditor.tsx
        CloudSoftwareAiInfrastructureEditor.tsx
        HousebuilderEditor.tsx
        ProfessionalServicesEditor.tsx
```

---

## 4. Core design principle

Every business model module must convert its own industry-specific assumptions into a common financial output.

The generic valuation layer should not know whether the company is Microsoft, Persimmon, or Gateley.

Each business model must return:

```text
revenue
gross_profit
operating_profit
tax
net_income
eps
operating_cash_flow
maintenance_investment
growth_investment
free_cash_flow
dividends
buybacks
share_count
book_value
net_debt
diagnostics
```

The generic valuation layer then calculates:

```text
terminal value
terminal share price
cumulative dividends
total return multiple
total return CAGR
probability distribution
histogram buckets
confidence overlay
valuation zone
sensitivity analysis
```

---

## 5. BusinessModel interface

Create a base protocol / abstract class.

```python
from dataclasses import dataclass
from typing import Protocol, Any
import numpy as np

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

class BusinessModel(Protocol):
    business_model_type: str

    def validate_inputs(self, scenario: dict) -> None:
        ...

    def simulate(
        self,
        scenario: dict,
        rng: np.random.Generator,
        simulation_count: int,
        horizon_years: int,
    ) -> OperatingModelResult:
        ...

    def sensitivity_variables(self) -> list[str]:
        ...

    def default_editor_schema(self) -> dict:
        ...
```

All business models must conform to this interface.

---

## 6. Business model registry

Create:

```text
business_models/registry.py
```

Example:

```python
from app.business_models.cloud_software_ai_infrastructure import CloudSoftwareAiInfrastructureModel
from app.business_models.housebuilder import HousebuilderModel
from app.business_models.professional_services import ProfessionalServicesModel
from app.business_models.generic_revenue_margin_fcf import GenericRevenueMarginFcfModel

_REGISTRY = {
    "generic_revenue_margin_fcf": GenericRevenueMarginFcfModel(),
    "cloud_software_ai_infrastructure": CloudSoftwareAiInfrastructureModel(),
    "housebuilder": HousebuilderModel(),
    "professional_services": ProfessionalServicesModel(),
}

def get_business_model(model_type: str):
    try:
        return _REGISTRY[model_type]
    except KeyError:
        raise ValueError(f"Unsupported business_model_type: {model_type}")
```

The simulation runner should select the model from:

```json
{
  "business_model_type": "housebuilder"
}
```

---

## 7. Common scenario schema

Create a generic top-level scenario format.

```json
{
  "meta": {
    "scenario_id": "msft_cloud_ai_default",
    "company": "Microsoft Corporation",
    "ticker": "MSFT",
    "exchange": "NASDAQ",
    "currency": "USD",
    "as_of_date": "2026-06-27",
    "description": "Microsoft cloud/software/AI infrastructure default prior scenario."
  },
  "business_model_type": "cloud_software_ai_infrastructure",
  "market": {
    "current_share_price": 372.97,
    "current_market_cap": 2776800000000,
    "diluted_shares": 7440000000,
    "current_eps": 16.8,
    "current_fcf_per_share": null,
    "net_debt": 0
  },
  "simulation": {
    "horizon_years": 10,
    "simulation_count": 20000,
    "random_seed": 42,
    "target_cagr": 0.12
  },
  "capital_return": {
    "dividend_policy_type": "payout_ratio",
    "dividend_payout_ratio": {
      "type": "pert",
      "min": 0.18,
      "mode": 0.22,
      "max": 0.28
    },
    "buyback_policy_type": "post_dividend_fcf_share",
    "buyback_pct_of_post_dividend_fcf": {
      "type": "pert",
      "min": 0.2,
      "mode": 0.45,
      "max": 0.75
    },
    "max_annual_share_count_reduction": 0.05
  },
  "valuation": {
    "methods": [
      {
        "method": "pe",
        "weight": 0.7,
        "terminal_multiple": {
          "type": "pert",
          "min": 15,
          "mode": 21,
          "max": 28
        }
      },
      {
        "method": "fcf_multiple",
        "weight": 0.3,
        "terminal_multiple": {
          "type": "pert",
          "min": 14,
          "mode": 20,
          "max": 27
        }
      }
    ],
    "net_debt_adjustment": true
  },
  "output": {
    "histogram": {
      "bucket_count": 20,
      "bucket_mode": "auto_percentile_trimmed",
      "lower_trim": 0.01,
      "upper_trim": 0.99,
      "include_overflow_buckets": true,
      "overlay_metric": "cumulative_probability"
    }
  },
  "business_model_inputs": {}
}
```

The `business_model_inputs` object is owned by the selected business model module.

---

## 8. Common output schema

All simulations should return the same response shape.

```json
{
  "summary": {
    "company": "Microsoft Corporation",
    "ticker": "MSFT",
    "business_model_type": "cloud_software_ai_infrastructure",
    "current_share_price": 372.97,
    "target_cagr": 0.12,
    "probability_above_target": 0.0,
    "probability_of_loss": 0.0,
    "mean_cagr": 0.0,
    "median_cagr": 0.0,
    "p10_cagr": 0.0,
    "p25_cagr": 0.0,
    "p50_cagr": 0.0,
    "p75_cagr": 0.0,
    "p90_cagr": 0.0,
    "valuation_zone": "Watchlist / fair"
  },
  "distribution": {
    "metric": "total_return_cagr",
    "bucket_count": 20,
    "target_cagr": 0.12,
    "probability_above_target": 0.0,
    "probability_below_target": 0.0,
    "buckets": []
  },
  "percentiles": [],
  "fan_chart": [],
  "diagnostics": {},
  "sensitivity": []
}
```

---

## 9. Generic valuation layer

Create:

```text
valuation/terminal_value.py
```

Supported terminal valuation methods:

```text
pe
fcf_multiple
ev_ebit
ev_ebitda
price_to_book
nav_discount
dividend_yield
```

MVP methods:

```text
pe
fcf_multiple
price_to_book
nav_discount
dividend_yield
```

The terminal value engine should read the methods array:

```json
"valuation": {
  "methods": [
    {
      "method": "pe",
      "weight": 0.5,
      "terminal_multiple": {}
    },
    {
      "method": "price_to_book",
      "weight": 0.3,
      "terminal_multiple": {}
    },
    {
      "method": "dividend_yield",
      "weight": 0.2,
      "terminal_yield": {}
    }
  ]
}
```

Rules:

```text
Weights must sum to 1.0.
If a valuation method requires a missing metric, fail validation with a useful error.
For example, price_to_book requires book_value.
Dividend_yield requires year-10 dividend per share.
```

---

## 10. Capital return module

Create:

```text
valuation/capital_returns.py
```

Support dividend policy types:

```text
payout_ratio
fixed_dividend_growth
dividend_per_share_distribution
residual_cash_after_reinvestment
```

Support buyback policy types:

```text
none
fixed_pct_market_cap
post_dividend_fcf_share
excess_cash_above_buffer
```

MVP:

```text
payout_ratio
fixed_dividend_growth
post_dividend_fcf_share
none
```

Buyback logic must be generic and applied after each business model calculates FCF.

Inputs:

```json
{
  "dividend_policy_type": "payout_ratio",
  "dividend_payout_ratio": {
    "type": "pert",
    "min": 0.18,
    "mode": 0.22,
    "max": 0.28
  },
  "buyback_policy_type": "post_dividend_fcf_share",
  "buyback_pct_of_post_dividend_fcf": {
    "type": "pert",
    "min": 0.2,
    "mode": 0.45,
    "max": 0.75
  },
  "max_annual_share_count_reduction": 0.05
}
```

For small UK stocks, buyback policy can default to:

```json
{
  "buyback_policy_type": "none"
}
```

---

## 11. Distribution / histogram module

Keep and generalise the probability histogram with confidence overlay.

Create:

```text
core/output_distribution.py
```

Function:

```python
def build_probability_distribution(
    values: np.ndarray,
    bucket_count: int,
    target_value: float,
    mode: str = "auto_percentile_trimmed",
    lower_trim: float = 0.01,
    upper_trim: float = 0.99,
    include_overflow_buckets: bool = True,
) -> dict:
    ...
```

Required invariants:

```text
Bucket probabilities sum to 1.0.
Cumulative probability is monotonic increasing.
Probability above target equals raw simulation result.
Target bucket is marked.
Overflow buckets are included by default.
```

This module is fully generic and must not import any business model.

---

## 12. Business model module 1 — generic revenue / margin / FCF

Create:

```text
business_models/generic_revenue_margin_fcf.py
```

Purpose:

A simple model for companies where the user does not need a detailed industry engine.

Inputs:

```json
{
  "starting_revenue": 1000,
  "revenue_growth": {
    "years_1_to_3": { "type": "pert", "min": 0.02, "mode": 0.05, "max": 0.08 },
    "years_4_to_7": { "type": "pert", "min": 0.01, "mode": 0.04, "max": 0.07 },
    "years_8_to_10": { "type": "pert", "min": 0.00, "mode": 0.03, "max": 0.06 }
  },
  "operating_margin": {
    "start": 0.15,
    "terminal": { "type": "pert", "min": 0.10, "mode": 0.15, "max": 0.20 }
  },
  "tax_rate": {
    "type": "pert",
    "min": 0.18,
    "mode": 0.22,
    "max": 0.26
  },
  "maintenance_investment_pct_revenue": {
    "type": "pert",
    "min": 0.02,
    "mode": 0.04,
    "max": 0.08
  },
  "growth_investment_pct_incremental_revenue": {
    "type": "pert",
    "min": 0.10,
    "mode": 0.30,
    "max": 0.60
  },
  "working_capital_pct_incremental_revenue": {
    "type": "pert",
    "min": 0.05,
    "mode": 0.10,
    "max": 0.20
  }
}
```

Model:

```text
revenue grows by sampled CAGRs
operating profit = revenue × operating margin
tax = operating profit × tax rate
net income = operating profit - tax
maintenance investment = revenue × maintenance investment %
growth investment = incremental revenue × growth investment %
working capital investment = incremental revenue × working capital %
FCF = net income - maintenance investment - growth investment - working capital investment
EPS = net income / share count
```

This module is the fallback for all companies without a specific model.

---

## 13. Business model module 2 — cloud/software/AI infrastructure

Move the current Microsoft model into:

```text
business_models/cloud_software_ai_infrastructure.py
```

This module should contain the current Microsoft-specific logic:

```text
revenue lines
gross margin by line
AI capex
short-lived asset share
GPU economic life
data-centre economic life
component cost changes
AI price crash shock
accelerated depreciation shock
terminal multiple haircut
```

Inputs should be under:

```json
"business_model_inputs": {
  "revenue_lines": [],
  "opex": {},
  "capex": {},
  "shock": {}
}
```

Keep the existing `msft_cloud_ai_default.json`, but move Microsoft assumptions into this structure.

---

## 14. Business model module 3 — housebuilder

Create:

```text
business_models/housebuilder.py
```

This supports Persimmon, Taylor Wimpey, Bellway, Berkeley, Vistry-style modelling.

### 14.1 Core inputs

```json
{
  "starting_completions": 11905,
  "starting_average_selling_price": 278000,
  "starting_outlets": 271,
  "starting_land_bank_plots": 80000,
  "starting_book_value": 3600000000,
  "starting_net_debt": -116000000,

  "completions_growth": {
    "years_1_to_3": { "type": "pert", "min": -0.05, "mode": 0.03, "max": 0.10 },
    "years_4_to_7": { "type": "pert", "min": -0.02, "mode": 0.02, "max": 0.06 },
    "years_8_to_10": { "type": "pert", "min": -0.02, "mode": 0.01, "max": 0.04 }
  },

  "asp_growth": {
    "years_1_to_3": { "type": "pert", "min": -0.04, "mode": 0.02, "max": 0.06 },
    "years_4_to_7": { "type": "pert", "min": -0.02, "mode": 0.03, "max": 0.06 },
    "years_8_to_10": { "type": "pert", "min": -0.01, "mode": 0.03, "max": 0.05 }
  },

  "gross_margin": {
    "start": 0.22,
    "terminal": { "type": "pert", "min": 0.16, "mode": 0.22, "max": 0.28 }
  },

  "operating_cost_pct_revenue": {
    "type": "pert",
    "min": 0.06,
    "mode": 0.08,
    "max": 0.10
  },

  "tax_rate": {
    "type": "pert",
    "min": 0.24,
    "mode": 0.25,
    "max": 0.27
  },

  "land_reinvestment_pct_revenue": {
    "type": "pert",
    "min": 0.08,
    "mode": 0.14,
    "max": 0.22
  },

  "working_capital_pct_revenue_change": {
    "type": "pert",
    "min": 0.10,
    "mode": 0.25,
    "max": 0.45
  }
}
```

### 14.2 Revenue formula

```text
revenue = completions × average_selling_price
```

### 14.3 Profit formula

```text
gross_profit = revenue × gross_margin
operating_profit = gross_profit - revenue × operating_cost_pct_revenue
tax = operating_profit × tax_rate
net_income = operating_profit - tax
```

### 14.4 Cash flow formula

```text
maintenance_investment = land_reinvestment_pct_revenue × revenue
growth_investment = positive_incremental_revenue × working_capital_pct_revenue_change
free_cash_flow = net_income - maintenance_investment - growth_investment
```

This is intentionally simplified. The point is to capture land/inventory cash absorption, not precise statutory cash flow.

### 14.5 Housebuilder shock

Add shock block:

```json
{
  "housing_downturn_shock": {
    "enabled": true,
    "probability": { "type": "pert", "min": 0.15, "mode": 0.30, "max": 0.50 },
    "shock_year": { "type": "pert_integer", "min": 1, "mode": 3, "max": 6 },
    "completions_decline": { "type": "pert", "min": 0.05, "mode": 0.15, "max": 0.30 },
    "asp_decline": { "type": "pert", "min": 0.03, "mode": 0.10, "max": 0.20 },
    "gross_margin_haircut": { "type": "pert", "min": 0.03, "mode": 0.07, "max": 0.12 },
    "land_write_down_probability_given_shock": { "type": "pert", "min": 0.05, "mode": 0.15, "max": 0.35 },
    "land_write_down_pct_book": { "type": "pert", "min": 0.02, "mode": 0.06, "max": 0.15 },
    "terminal_pb_haircut": { "type": "pert", "min": 0.05, "mode": 0.15, "max": 0.30 }
  }
}
```

### 14.6 Housebuilder valuation

Default terminal valuation blend:

```json
{
  "methods": [
    {
      "method": "pe",
      "weight": 0.45,
      "terminal_multiple": { "type": "pert", "min": 7, "mode": 10, "max": 14 }
    },
    {
      "method": "price_to_book",
      "weight": 0.35,
      "terminal_multiple": { "type": "pert", "min": 0.7, "mode": 1.0, "max": 1.4 }
    },
    {
      "method": "dividend_yield",
      "weight": 0.20,
      "terminal_yield": { "type": "pert", "min": 0.04, "mode": 0.06, "max": 0.09 }
    }
  ]
}
```

---

## 15. Business model module 4 — professional services

Create:

```text
business_models/professional_services.py
```

This supports Gateley, FRP, Begbies, Keystone Law and similar people-driven service businesses.

### 15.1 Core inputs

```json
{
  "starting_revenue": 193000000,
  "starting_operating_margin": 0.111,
  "starting_net_debt": 25300000,
  "starting_book_value": null,

  "organic_revenue_growth": {
    "years_1_to_3": { "type": "pert", "min": -0.02, "mode": 0.04, "max": 0.10 },
    "years_4_to_7": { "type": "pert", "min": 0.00, "mode": 0.04, "max": 0.08 },
    "years_8_to_10": { "type": "pert", "min": 0.00, "mode": 0.03, "max": 0.06 }
  },

  "acquired_revenue_addition_pct": {
    "years_1_to_3": { "type": "pert", "min": 0.00, "mode": 0.03, "max": 0.10 },
    "years_4_to_7": { "type": "pert", "min": 0.00, "mode": 0.02, "max": 0.06 },
    "years_8_to_10": { "type": "pert", "min": 0.00, "mode": 0.01, "max": 0.04 }
  },

  "operating_margin": {
    "start": 0.111,
    "terminal": { "type": "pert", "min": 0.08, "mode": 0.12, "max": 0.16 }
  },

  "tax_rate": {
    "type": "pert",
    "min": 0.23,
    "mode": 0.25,
    "max": 0.27
  },

  "working_capital_pct_incremental_revenue": {
    "type": "pert",
    "min": 0.10,
    "mode": 0.25,
    "max": 0.45
  },

  "maintenance_capex_pct_revenue": {
    "type": "pert",
    "min": 0.005,
    "mode": 0.015,
    "max": 0.03
  },

  "acquisition_spend_multiple_of_acquired_revenue": {
    "type": "pert",
    "min": 0.6,
    "mode": 1.0,
    "max": 1.6
  }
}
```

### 15.2 Revenue formula

```text
organic_revenue = prior_revenue × organic_growth
acquired_revenue = prior_revenue × acquired_revenue_addition_pct
revenue = prior_revenue + organic_revenue + acquired_revenue
```

### 15.3 Profit formula

```text
operating_profit = revenue × operating_margin
tax = operating_profit × tax_rate
net_income = operating_profit - tax
```

### 15.4 Cash flow formula

```text
working_capital_investment = positive_incremental_revenue × working_capital_pct_incremental_revenue
maintenance_capex = revenue × maintenance_capex_pct_revenue
acquisition_spend = acquired_revenue × acquisition_spend_multiple_of_acquired_revenue

free_cash_flow =
  net_income
  - working_capital_investment
  - maintenance_capex
  - acquisition_spend
```

### 15.5 Professional services shock

Add shock block:

```json
{
  "transactional_downturn_shock": {
    "enabled": true,
    "probability": { "type": "pert", "min": 0.10, "mode": 0.25, "max": 0.45 },
    "shock_year": { "type": "pert_integer", "min": 1, "mode": 3, "max": 6 },
    "revenue_decline": { "type": "pert", "min": 0.03, "mode": 0.10, "max": 0.20 },
    "operating_margin_haircut": { "type": "pert", "min": 0.02, "mode": 0.04, "max": 0.08 },
    "working_capital_stretch_pct_revenue": { "type": "pert", "min": 0.02, "mode": 0.05, "max": 0.10 },
    "terminal_pe_haircut": { "type": "pert", "min": 0.05, "mode": 0.15, "max": 0.30 }
  }
}
```

### 15.6 Professional services valuation

Default terminal valuation blend:

```json
{
  "methods": [
    {
      "method": "pe",
      "weight": 0.65,
      "terminal_multiple": { "type": "pert", "min": 7, "mode": 11, "max": 16 }
    },
    {
      "method": "fcf_multiple",
      "weight": 0.35,
      "terminal_multiple": { "type": "pert", "min": 6, "mode": 10, "max": 15 }
    }
  ]
}
```

---

## 16. Frontend adaptation

### 16.1 Company selector

Add a company/scenario selector at the top of the app:

```text
Microsoft — Cloud/software/AI infrastructure
Persimmon — Housebuilder
Gateley — Professional services
Generic company — Revenue/margin/FCF
```

Selecting a company loads its default scenario JSON.

### 16.2 Dynamic editor rendering

Create a top-level component:

```text
BusinessModelEditor.tsx
```

Pseudo-code:

```typescript
switch (scenario.businessModelType) {
  case "cloud_software_ai_infrastructure":
    return <CloudSoftwareAiInfrastructureEditor />
  case "housebuilder":
    return <HousebuilderEditor />
  case "professional_services":
    return <ProfessionalServicesEditor />
  case "generic_revenue_margin_fcf":
    return <GenericRevenueMarginFcfEditor />
}
```

Common editors always shown:

```text
Market inputs
Simulation settings
Capital return settings
Terminal valuation settings
Histogram/output settings
```

Business-specific editors shown underneath.

### 16.3 Common output visualisations

The same output components should work for every company:

```text
ValuationDashboard
ProbabilityHistogramWithConfidenceOverlay
PercentileTable
FanChart
SensitivityChart
```

Business-specific diagnostic panels can be optional.

Examples:

```text
Microsoft diagnostics:
  AI revenue
  AI capex/revenue
  maintenance capex/revenue
  GPU asset base
  cloud gross margin

Persimmon diagnostics:
  completions
  ASP
  gross margin
  land reinvestment
  book value per share
  P/B terminal valuation

Gateley diagnostics:
  organic growth
  acquired revenue
  operating margin
  acquisition spend
  working capital absorption
  net debt
```

---

## 17. API changes

### 17.1 `GET /api/scenarios`

Returns available scenarios:

```json
[
  {
    "scenario_id": "msft_cloud_ai_default",
    "company": "Microsoft Corporation",
    "ticker": "MSFT",
    "business_model_type": "cloud_software_ai_infrastructure"
  },
  {
    "scenario_id": "psn_housebuilder_default",
    "company": "Persimmon",
    "ticker": "PSN.L",
    "business_model_type": "housebuilder"
  },
  {
    "scenario_id": "gtly_professional_services_default",
    "company": "Gateley Holdings",
    "ticker": "GTLY.L",
    "business_model_type": "professional_services"
  }
]
```

### 17.2 `GET /api/scenarios/{scenario_id}`

Returns full scenario JSON.

### 17.3 `POST /api/simulate`

Accepts any valid scenario.

Internally:

```text
read business_model_type
load business model from registry
validate scenario
run business model simulation
apply generic capital returns if not done inside model
apply terminal valuation
build distribution
return common output
```

### 17.4 `POST /api/sensitivity`

Accepts any valid scenario.

Uses selected business model’s `sensitivity_variables()` plus common valuation variables.

---

## 18. Scenario defaults to create

### 18.1 Microsoft scenario

Filename:

```text
data/scenarios/msft_cloud_ai_default.json
```

Use existing Microsoft priors.

Business model type:

```json
"business_model_type": "cloud_software_ai_infrastructure"
```

### 18.2 Persimmon scenario

Filename:

```text
data/scenarios/psn_housebuilder_default.json
```

Use rough priors:

```json
{
  "meta": {
    "scenario_id": "psn_housebuilder_default",
    "company": "Persimmon",
    "ticker": "PSN.L",
    "exchange": "LSE",
    "currency": "GBP",
    "as_of_date": "2026-06-27"
  },
  "business_model_type": "housebuilder",
  "market": {
    "current_share_price": 10.70,
    "diluted_shares": 320000000,
    "current_eps": null,
    "current_fcf_per_share": null,
    "net_debt": -116000000
  },
  "business_model_inputs": {
    "starting_completions": 11905,
    "starting_average_selling_price": 278000,
    "starting_outlets": 271,
    "starting_land_bank_plots": 80000,
    "starting_book_value": 3600000000,
    "starting_net_debt": -116000000
  }
}
```

Note: leave full priors in the housebuilder template. The scenario can override only values that differ.

### 18.3 Gateley scenario

Filename:

```text
data/scenarios/gtly_professional_services_default.json
```

Use rough priors:

```json
{
  "meta": {
    "scenario_id": "gtly_professional_services_default",
    "company": "Gateley Holdings",
    "ticker": "GTLY.L",
    "exchange": "AIM",
    "currency": "GBP",
    "as_of_date": "2026-06-27"
  },
  "business_model_type": "professional_services",
  "market": {
    "current_share_price": 0.55,
    "diluted_shares": 130000000,
    "current_eps": null,
    "current_fcf_per_share": null,
    "net_debt": 25300000
  },
  "business_model_inputs": {
    "starting_revenue": 193000000,
    "starting_operating_margin": 0.111,
    "starting_net_debt": 25300000
  }
}
```

Note: the exact share price and share count should remain editable. Do not hard-code them into the model.

---

## 19. Sensitivity refactor

Sensitivity must support common and business-specific variables.

Common variables:

```text
terminal_pe
terminal_fcf_multiple
terminal_price_to_book
terminal_dividend_yield
dividend_payout_ratio
buyback_pct_of_fcf
tax_rate
```

Microsoft-specific:

```text
azure_ai_growth
azure_ai_margin
gpu_economic_life
ai_price_crash_probability
ai_capex_intensity
terminal_multiple_haircut
```

Housebuilder-specific:

```text
completions_growth
average_selling_price_growth
gross_margin
land_reinvestment_pct_revenue
housing_downturn_probability
price_to_book_terminal_multiple
```

Professional-services-specific:

```text
organic_revenue_growth
operating_margin
working_capital_absorption
acquisition_spend_multiple
transactional_downturn_probability
terminal_pe
```

---

## 20. Migration plan

### Phase 1 — extract generic engine

1. Move PERT and fixed distributions into `core/distributions.py`.
2. Move histogram / confidence overlay logic into `core/output_distribution.py`.
3. Move terminal valuation into `valuation/terminal_value.py`.
4. Move capital return logic into `valuation/capital_returns.py`.
5. Create common output dataclasses / Pydantic schemas.
6. Confirm existing Microsoft simulation still passes tests.

### Phase 2 — create business model interface

1. Create `business_models/base.py`.
2. Create `OperatingModelResult`.
3. Create `BusinessModel` protocol.
4. Create `business_models/registry.py`.
5. Wrap current Microsoft model as `cloud_software_ai_infrastructure`.
6. Confirm `/api/simulate` uses registry rather than directly calling Microsoft model.

### Phase 3 — add generic model

1. Implement `generic_revenue_margin_fcf.py`.
2. Create `generic_default.json`.
3. Add smoke tests.
4. Add frontend editor.

### Phase 4 — add housebuilder model

1. Implement `housebuilder.py`.
2. Create `psn_housebuilder_default.json`.
3. Add housebuilder shock logic.
4. Add PE / P/B / dividend-yield valuation blend.
5. Add housebuilder diagnostics.
6. Add frontend editor.
7. Add smoke tests.

### Phase 5 — add professional services model

1. Implement `professional_services.py`.
2. Create `gtly_professional_services_default.json`.
3. Add transactional downturn shock.
4. Add acquisition and working-capital cash-flow logic.
5. Add frontend editor.
6. Add smoke tests.

### Phase 6 — frontend unification

1. Add scenario/company selector.
2. Add dynamic business-model editor rendering.
3. Ensure common charts work for all business types.
4. Add business-specific diagnostics panels.
5. Add save/load scenario JSON.
6. Add export simulation results.

### Phase 7 — quality and guardrails

1. Add validation for impossible assumptions.
2. Add warnings for missing current share price or shares.
3. Add tests for all modules.
4. Add README explaining how to add a new business model.
5. Add examples for Microsoft, Persimmon, Gateley.

---

## 21. Validation rules

Add validation failures for:

```text
missing current_share_price
missing diluted_shares
terminal valuation weights not summing to 1.0
negative revenue
negative share count
non-finite simulation output
invalid business_model_type
unsupported terminal valuation method
missing book_value when price_to_book is used
missing dividend per share when dividend_yield valuation is used
negative histogram bucket count
```

Add validation warnings for:

```text
target CAGR above 20%
simulation count below 1,000
terminal PE above 35x
terminal P/B above 3x for housebuilders
FCF persistently negative
net debt / operating profit above 4x
buybacks enabled while FCF is negative
```

Warnings should not block simulation unless the assumption is mathematically invalid.

---

## 22. Acceptance criteria

The refactor is complete when:

1. Existing Microsoft scenario still works.
2. Microsoft uses `business_model_type = cloud_software_ai_infrastructure`.
3. Generic model runs from a default scenario.
4. Persimmon housebuilder scenario runs.
5. Gateley professional-services scenario runs.
6. All scenarios return the same output schema.
7. Histogram with confidence overlay works for all scenarios.
8. Target CAGR probability works for all scenarios.
9. Terminal valuation supports PE, FCF multiple, P/B and dividend yield.
10. Frontend can switch between scenarios.
11. Frontend renders business-specific editors.
12. Frontend renders common output charts for all models.
13. Sensitivity analysis works with common and business-specific variables.
14. Scenario JSON can be saved and reloaded.
15. Backend tests pass.
16. No simulation returns NaN, infinite values, or negative share count.
17. README explains how to add a new business model plugin.

---

## 23. README addition — adding a new stock

Add a README section:

```text
To add a new stock:

1. Choose an existing business_model_type.
2. Create a scenario JSON file under data/scenarios.
3. Set market inputs:
   - current_share_price
   - diluted_shares
   - current EPS if available
   - net debt
4. Add business_model_inputs for the selected model.
5. Set valuation method blend.
6. Run the scenario.
7. Review diagnostics and sensitivity.
8. Adjust priors if the output is economically incoherent.
```

Add another README section:

```text
To add a new business model:

1. Create a new file in business_models.
2. Implement the BusinessModel protocol.
3. Return OperatingModelResult.
4. Add it to registry.py.
5. Add a default scenario.
6. Add a frontend editor.
7. Add smoke tests.
8. Add sensitivity variables.
```

---

## 24. Final design intent

The platform should not try to produce precise forecasts.

It should produce comparable probabilistic underwriting outputs across very different stocks:

```text
P(CAGR >= target)
P(loss)
P10 / P50 / P90 CAGR
P10 / P50 / P90 terminal share price
key sensitivity drivers
valuation zone
```

The useful abstraction is:

```text
Which stock gives the best probability-weighted return distribution for the specific risks being underwritten?
```

Not:

```text
What is the exact fair value?
```
