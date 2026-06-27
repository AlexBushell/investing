from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from app.business_models.base import RegimeDefinition
from app.model.assumptions import DistributionSpec, GrowthPeriods, Scenario, TerminalMarginSpec
from app.model.distributions import clamp, interpolate_linear, safe_divide, sample_distribution
from app.model.financials import REGIME_BALANCED, SimulationArrays
from app.valuation.capital_returns import apply_capital_returns_for_year, sample_capital_return_policy
from app.valuation.terminal_value import (
    sample_terminal_multiples,
    total_return_cagr,
    weighted_pe_fcf_terminal_share_price,
)


class GenericRevenueMarginFcfInputs(BaseModel):
    starting_revenue_bn: float
    revenue_growth: GrowthPeriods
    operating_margin: TerminalMarginSpec
    maintenance_investment_pct_revenue: DistributionSpec
    growth_investment_pct_incremental_revenue: DistributionSpec
    working_capital_pct_incremental_revenue: DistributionSpec
    tax_rate: DistributionSpec | None = None


class GenericRevenueMarginFcfModel:
    business_model_type = "generic_revenue_margin_fcf"

    def validate_inputs(self, scenario: Scenario) -> None:
        GenericRevenueMarginFcfInputs.model_validate(scenario.business_model_inputs)

    def simulate(
        self,
        scenario: Scenario,
        rng: np.random.Generator,
        simulation_count: int,
    ) -> SimulationArrays:
        inputs = GenericRevenueMarginFcfInputs.model_validate(scenario.business_model_inputs)
        horizon = scenario.simulation.horizon_years

        tax_spec = inputs.tax_rate or scenario.simulation.tax_rate
        tax_rate = clamp(sample_distribution(tax_spec, simulation_count, rng), 0.0, 0.5)
        growth_samples = {
            "years_1_to_3": sample_distribution(inputs.revenue_growth.years_1_to_3, simulation_count, rng),
            "years_4_to_7": sample_distribution(inputs.revenue_growth.years_4_to_7, simulation_count, rng),
            "years_8_to_10": sample_distribution(inputs.revenue_growth.years_8_to_10, simulation_count, rng),
        }
        terminal_margin = clamp(
            sample_distribution(inputs.operating_margin.terminal, simulation_count, rng),
            -0.5,
            0.8,
        )
        margin_path = interpolate_linear(inputs.operating_margin.start, terminal_margin, horizon)
        maintenance_pct = clamp(
            sample_distribution(inputs.maintenance_investment_pct_revenue, simulation_count, rng),
            0.0,
            1.0,
        )
        growth_investment_pct = clamp(
            sample_distribution(inputs.growth_investment_pct_incremental_revenue, simulation_count, rng),
            0.0,
            5.0,
        )
        working_capital_pct = clamp(
            sample_distribution(inputs.working_capital_pct_incremental_revenue, simulation_count, rng),
            0.0,
            5.0,
        )

        capital_return_policy = sample_capital_return_policy(
            scenario,
            simulation_count,
            rng,
            dividend_payout_cap=1.0,
            max_share_reduction_cap=0.25,
        )
        terminal_multiples = sample_terminal_multiples(scenario, simulation_count, rng, minimum=1.0)
        terminal_pe = terminal_multiples.terminal_pe
        terminal_fcf_multiple = terminal_multiples.terminal_fcf_multiple

        revenue = np.zeros((simulation_count, horizon), dtype=float)
        gross_profit = np.zeros((simulation_count, horizon), dtype=float)
        operating_income = np.zeros((simulation_count, horizon), dtype=float)
        net_income = np.zeros((simulation_count, horizon), dtype=float)
        eps = np.zeros((simulation_count, horizon), dtype=float)
        depreciation = np.zeros((simulation_count, horizon), dtype=float)
        fcf = np.zeros((simulation_count, horizon), dtype=float)
        total_capex = np.zeros((simulation_count, horizon), dtype=float)
        maintenance_investment = np.zeros((simulation_count, horizon), dtype=float)
        growth_investment = np.zeros((simulation_count, horizon), dtype=float)
        share_count = np.zeros((simulation_count, horizon), dtype=float)
        operating_margin = np.zeros((simulation_count, horizon), dtype=float)
        dividends_per_share = np.zeros((simulation_count, horizon), dtype=float)

        prior_revenue = np.full(simulation_count, inputs.starting_revenue_bn, dtype=float)
        prior_share_count = np.full(simulation_count, scenario.market.estimated_diluted_shares_bn, dtype=float)
        current_normalized_pe = scenario.market.current_share_price / max(
            scenario.market.current_normalized_eps_ttm,
            0.01,
        )

        for year_index in range(horizon):
            year_number = year_index + 1
            if year_number <= 3:
                growth_rate = growth_samples["years_1_to_3"]
            elif year_number <= 7:
                growth_rate = growth_samples["years_4_to_7"]
            else:
                growth_rate = growth_samples["years_8_to_10"]

            revenue[:, year_index] = np.maximum(prior_revenue * (1.0 + growth_rate), 0.0)
            incremental_revenue = np.maximum(revenue[:, year_index] - prior_revenue, 0.0)
            operating_margin[:, year_index] = margin_path[:, year_index]
            operating_income[:, year_index] = revenue[:, year_index] * operating_margin[:, year_index]
            gross_profit[:, year_index] = operating_income[:, year_index]
            tax = np.maximum(operating_income[:, year_index], 0.0) * tax_rate
            net_income[:, year_index] = operating_income[:, year_index] - tax

            maintenance_investment[:, year_index] = revenue[:, year_index] * maintenance_pct
            growth_capex = incremental_revenue * growth_investment_pct
            working_capital_investment = incremental_revenue * working_capital_pct
            growth_investment[:, year_index] = growth_capex + working_capital_investment
            total_capex[:, year_index] = maintenance_investment[:, year_index] + growth_investment[:, year_index]
            depreciation[:, year_index] = maintenance_investment[:, year_index]
            fcf[:, year_index] = net_income[:, year_index] - total_capex[:, year_index]

            rolling_pe = current_normalized_pe + (terminal_pe - current_normalized_pe) * (year_number / horizon)
            estimated_share_price = np.maximum(safe_divide(net_income[:, year_index], prior_share_count), 0.01) * rolling_pe
            capital_return = apply_capital_returns_for_year(
                net_income=net_income[:, year_index],
                free_cash_flow=fcf[:, year_index],
                prior_share_count=prior_share_count,
                estimated_share_price=estimated_share_price,
                policy=capital_return_policy,
            )
            dividends_per_share[:, year_index] = capital_return.dividends_per_share
            share_count[:, year_index] = capital_return.ending_share_count
            eps[:, year_index] = safe_divide(net_income[:, year_index], share_count[:, year_index])

            prior_revenue = revenue[:, year_index]
            prior_share_count = share_count[:, year_index]

        terminal_share_price = weighted_pe_fcf_terminal_share_price(
            scenario=scenario,
            terminal_eps=eps[:, -1],
            terminal_fcf=fcf[:, -1],
            terminal_share_count=share_count[:, -1],
            terminal_pe=terminal_pe,
            terminal_fcf_multiple=terminal_fcf_multiple,
        )
        ending_value_per_share, cagr = total_return_cagr(
            terminal_share_price=terminal_share_price,
            dividends_per_share=dividends_per_share,
            current_share_price=scenario.market.current_share_price,
            horizon_years=horizon,
        )

        return SimulationArrays(
            revenue=revenue,
            gross_profit=gross_profit,
            operating_income=operating_income,
            net_income=net_income,
            eps=eps,
            depreciation=depreciation,
            fcf=fcf,
            total_capex=total_capex,
            maintenance_capex=maintenance_investment,
            growth_capex=growth_investment,
            share_count=share_count,
            total_gross_margin=operating_margin,
            operating_margin=operating_margin,
            dividends_per_share=dividends_per_share,
            terminal_pe=terminal_pe,
            terminal_fcf_multiple=terminal_fcf_multiple,
            regime_code=np.full(simulation_count, REGIME_BALANCED, dtype=int),
            shock_occurs=np.zeros(simulation_count, dtype=bool),
            accelerated_depreciation_occurs=np.zeros(simulation_count, dtype=bool),
            terminal_share_price=terminal_share_price,
            ending_value_per_share=ending_value_per_share,
            cagr=cagr,
        )

    def sensitivity_variables(self) -> list[str]:
        return [
            "terminal_pe",
            "terminal_fcf_multiple",
            "generic_revenue_growth",
            "generic_operating_margin",
            "generic_reinvestment",
        ]

    def regime_definitions(self) -> list[RegimeDefinition]:
        return [
            RegimeDefinition(
                key="balanced",
                label="Base operating range",
                description="Generic revenue, margin, reinvestment, and valuation assumptions without a separate scenario shock.",
                code=REGIME_BALANCED,
            )
        ]

    def default_editor_schema(self) -> dict[str, Any]:
        return {
            "common": ["market", "simulation", "valuation", "capital_return", "histogram"],
            "business_specific": ["business_model_inputs"],
        }
