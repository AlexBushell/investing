from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from app.business_models.base import RegimeDefinition
from app.model.assumptions import DistributionSpec, GrowthPeriods, Scenario, TerminalMarginSpec
from app.model.distributions import clamp, interpolate_linear, safe_divide, sample_distribution
from app.model.financials import (
    REGIME_BALANCED,
    REGIME_DISAPPOINTMENT,
    REGIME_OVERBUILD,
    REGIME_SCARCITY,
    SimulationArrays,
)
from app.valuation.capital_returns import apply_capital_returns_for_year, sample_capital_return_policy
from app.valuation.terminal_value import sample_terminal_multiples, total_return_cagr, weighted_terminal_share_price


class GymShockInputs(BaseModel):
    enabled: bool = True
    probability: DistributionSpec
    shock_year: DistributionSpec
    revenue_per_site_haircut: DistributionSpec
    revenue_per_site_boost: DistributionSpec | None = None
    margin_haircut: DistributionSpec
    new_site_reduction: DistributionSpec
    terminal_multiple_haircut: DistributionSpec


class LowCostGymInputs(BaseModel):
    starting_sites: float
    starting_revenue_bn: float
    starting_non_property_net_debt_bn: float
    starting_lease_liability_bn: float
    new_sites_per_year: GrowthPeriods
    revenue_per_site_growth: GrowthPeriods
    cash_ebitda_less_rent_margin: TerminalMarginSpec
    maintenance_capex_pct_revenue: DistributionSpec
    growth_capex_per_new_site_bn: DistributionSpec
    depreciation_pct_gross_capex: DistributionSpec
    lease_liability_per_site_bn: DistributionSpec
    lease_liability_decay_pct: DistributionSpec
    cash_interest_rate: DistributionSpec
    tax_rate: DistributionSpec | None = None
    consumer_squeeze_shock: GymShockInputs | None = None


class LowCostGymIfrs16Model:
    business_model_type = "low_cost_gym_ifrs16"

    def validate_inputs(self, scenario: Scenario) -> None:
        LowCostGymInputs.model_validate(scenario.business_model_inputs)

    def simulate(
        self,
        scenario: Scenario,
        rng: np.random.Generator,
        simulation_count: int,
    ) -> SimulationArrays:
        inputs = LowCostGymInputs.model_validate(scenario.business_model_inputs)
        horizon = scenario.simulation.horizon_years

        tax_spec = inputs.tax_rate or scenario.simulation.tax_rate
        tax_rate = clamp(sample_distribution(tax_spec, simulation_count, rng), 0.0, 0.5)
        new_sites_samples = _sample_growth_periods(inputs.new_sites_per_year, simulation_count, rng)
        revenue_per_site_growth = _sample_growth_periods(inputs.revenue_per_site_growth, simulation_count, rng)
        terminal_cash_margin = clamp(
            sample_distribution(inputs.cash_ebitda_less_rent_margin.terminal, simulation_count, rng),
            0.05,
            0.45,
        )
        cash_margin_path = interpolate_linear(inputs.cash_ebitda_less_rent_margin.start, terminal_cash_margin, horizon)
        maintenance_capex_pct = clamp(
            sample_distribution(inputs.maintenance_capex_pct_revenue, simulation_count, rng),
            0.0,
            0.25,
        )
        growth_capex_per_site = clamp(
            sample_distribution(inputs.growth_capex_per_new_site_bn, simulation_count, rng),
            0.0,
            None,
        )
        depreciation_pct_gross_capex = clamp(
            sample_distribution(inputs.depreciation_pct_gross_capex, simulation_count, rng),
            0.0,
            1.0,
        )
        lease_liability_per_site = clamp(
            sample_distribution(inputs.lease_liability_per_site_bn, simulation_count, rng),
            0.0,
            None,
        )
        lease_decay = clamp(sample_distribution(inputs.lease_liability_decay_pct, simulation_count, rng), 0.0, 0.5)
        interest_rate = clamp(sample_distribution(inputs.cash_interest_rate, simulation_count, rng), 0.0, 0.25)
        capital_return_policy = sample_capital_return_policy(
            scenario,
            simulation_count,
            rng,
            dividend_payout_cap=1.0,
            max_share_reduction_cap=0.10,
        )
        terminal_multiples = sample_terminal_multiples(scenario, simulation_count, rng, minimum=1.0)
        terminal_pe = terminal_multiples.terminal_pe
        terminal_fcf_multiple = terminal_multiples.terminal_fcf_multiple

        shock = inputs.consumer_squeeze_shock
        if shock and shock.enabled:
            shock_probability = clamp(sample_distribution(shock.probability, simulation_count, rng), 0.0, 1.0)
            shock_occurs = rng.random(simulation_count) < shock_probability
            shock_year = np.clip(sample_distribution(shock.shock_year, simulation_count, rng).astype(int), 1, horizon)
            revenue_haircut = clamp(sample_distribution(shock.revenue_per_site_haircut, simulation_count, rng), 0.0, 0.8)
            revenue_boost = (
                clamp(sample_distribution(shock.revenue_per_site_boost, simulation_count, rng), 0.0, 0.5)
                if shock.revenue_per_site_boost is not None
                else np.zeros(simulation_count, dtype=float)
            )
            margin_haircut = clamp(sample_distribution(shock.margin_haircut, simulation_count, rng), 0.0, 0.3)
            new_site_reduction = clamp(sample_distribution(shock.new_site_reduction, simulation_count, rng), 0.0, 1.0)
            terminal_multiple_haircut = clamp(
                sample_distribution(shock.terminal_multiple_haircut, simulation_count, rng),
                0.0,
                0.8,
            )
        else:
            shock_occurs = np.zeros(simulation_count, dtype=bool)
            shock_year = np.full(simulation_count, horizon + 1, dtype=int)
            revenue_haircut = np.zeros(simulation_count, dtype=float)
            revenue_boost = np.zeros(simulation_count, dtype=float)
            margin_haircut = np.zeros(simulation_count, dtype=float)
            new_site_reduction = np.zeros(simulation_count, dtype=float)
            terminal_multiple_haircut = np.zeros(simulation_count, dtype=float)

        revenue = np.zeros((simulation_count, horizon), dtype=float)
        gross_profit = np.zeros((simulation_count, horizon), dtype=float)
        operating_income = np.zeros((simulation_count, horizon), dtype=float)
        net_income = np.zeros((simulation_count, horizon), dtype=float)
        eps = np.zeros((simulation_count, horizon), dtype=float)
        depreciation = np.zeros((simulation_count, horizon), dtype=float)
        fcf = np.zeros((simulation_count, horizon), dtype=float)
        total_capex = np.zeros((simulation_count, horizon), dtype=float)
        maintenance_capex = np.zeros((simulation_count, horizon), dtype=float)
        growth_capex = np.zeros((simulation_count, horizon), dtype=float)
        share_count = np.zeros((simulation_count, horizon), dtype=float)
        total_gross_margin = np.zeros((simulation_count, horizon), dtype=float)
        operating_margin = np.zeros((simulation_count, horizon), dtype=float)
        dividends_per_share = np.zeros((simulation_count, horizon), dtype=float)

        prior_sites = np.full(simulation_count, inputs.starting_sites, dtype=float)
        prior_revenue_per_site = np.full(
            simulation_count,
            inputs.starting_revenue_bn / max(inputs.starting_sites, 1e-9),
            dtype=float,
        )
        prior_share_count = np.full(simulation_count, scenario.market.estimated_diluted_shares_bn, dtype=float)
        non_property_net_debt = np.full(simulation_count, inputs.starting_non_property_net_debt_bn, dtype=float)
        lease_liability = np.full(simulation_count, inputs.starting_lease_liability_bn, dtype=float)
        cumulative_gross_capex = np.zeros(simulation_count, dtype=float)
        current_normalized_pe = scenario.market.current_share_price / max(
            scenario.market.current_normalized_eps_ttm,
            0.01,
        )

        for year_index in range(horizon):
            year_number = year_index + 1
            post_shock_mask = shock_occurs & (year_number >= shock_year)
            shock_hits_this_year = shock_occurs & (year_number == shock_year)
            new_sites = np.maximum(_growth_for_year(new_sites_samples, year_number), 0.0)
            new_sites = np.where(post_shock_mask, new_sites * (1.0 - new_site_reduction), new_sites)
            site_count = prior_sites + new_sites

            revenue_per_site = prior_revenue_per_site * (1.0 + _growth_for_year(revenue_per_site_growth, year_number))
            revenue_per_site = np.where(
                shock_hits_this_year,
                revenue_per_site * (1.0 - revenue_haircut + revenue_boost),
                revenue_per_site,
            )
            revenue[:, year_index] = np.maximum(site_count * revenue_per_site, 0.0)

            cash_margin = clamp(
                cash_margin_path[:, year_index] - np.where(post_shock_mask, margin_haircut, 0.0),
                0.02,
                0.45,
            )
            cash_ebitda_less_rent = revenue[:, year_index] * cash_margin
            maintenance_capex[:, year_index] = revenue[:, year_index] * maintenance_capex_pct
            growth_capex[:, year_index] = new_sites * growth_capex_per_site
            total_capex[:, year_index] = maintenance_capex[:, year_index] + growth_capex[:, year_index]
            cumulative_gross_capex = cumulative_gross_capex + total_capex[:, year_index]
            depreciation[:, year_index] = cumulative_gross_capex * depreciation_pct_gross_capex / 7.0

            lease_liability = np.maximum(lease_liability * (1.0 - lease_decay) + new_sites * lease_liability_per_site, 0.0)
            interest = np.maximum(non_property_net_debt, 0.0) * interest_rate
            operating_income[:, year_index] = cash_ebitda_less_rent - depreciation[:, year_index]
            operating_margin[:, year_index] = safe_divide(operating_income[:, year_index], revenue[:, year_index])
            total_gross_margin[:, year_index] = cash_margin
            gross_profit[:, year_index] = cash_ebitda_less_rent
            taxable_profit = np.maximum(cash_ebitda_less_rent - depreciation[:, year_index] - interest, 0.0)
            tax = taxable_profit * tax_rate
            net_income[:, year_index] = cash_ebitda_less_rent - depreciation[:, year_index] - interest - tax
            fcf[:, year_index] = cash_ebitda_less_rent - maintenance_capex[:, year_index] - growth_capex[:, year_index] - interest - tax

            current_eps_base = safe_divide(net_income[:, year_index], prior_share_count)
            rolling_pe = current_normalized_pe + (terminal_pe - current_normalized_pe) * (year_number / horizon)
            estimated_share_price = np.maximum(current_eps_base, 0.01) * rolling_pe
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

            residual_fcf = fcf[:, year_index] - capital_return.dividends_paid - capital_return.buyback_cash
            non_property_net_debt = np.maximum(non_property_net_debt - residual_fcf, -0.25)
            prior_sites = site_count
            prior_revenue_per_site = revenue_per_site
            prior_share_count = share_count[:, year_index]

        lease_leverage = safe_divide(lease_liability, np.maximum(gross_profit[:, -1], 1e-9))
        net_debt_leverage = safe_divide(np.maximum(non_property_net_debt, 0.0), np.maximum(gross_profit[:, -1], 1e-9))
        expansion_mask = (
            (new_sites_samples["years_1_to_3"] >= 22.0)
            & (terminal_cash_margin >= inputs.cash_ebitda_less_rent_margin.start)
            & (lease_leverage <= 3.75)
        )
        lease_pressure_mask = (lease_leverage >= 4.25) | (net_debt_leverage >= 1.4)
        squeeze_mask = shock_occurs & ~lease_pressure_mask
        regime_code = np.full(simulation_count, REGIME_BALANCED, dtype=int)
        regime_code[expansion_mask] = REGIME_SCARCITY
        regime_code[squeeze_mask] = REGIME_DISAPPOINTMENT
        regime_code[lease_pressure_mask] = REGIME_OVERBUILD

        terminal_pe = np.where(shock_occurs, terminal_pe * (1.0 - terminal_multiple_haircut), terminal_pe)
        terminal_fcf_multiple = np.where(
            shock_occurs,
            terminal_fcf_multiple * (1.0 - terminal_multiple_haircut),
            terminal_fcf_multiple,
        )
        terminal_share_price = weighted_terminal_share_price(
            scenario=scenario,
            terminal_eps=eps[:, -1],
            terminal_fcf=fcf[:, -1],
            terminal_share_count=share_count[:, -1],
            terminal_pe=terminal_pe,
            terminal_fcf_multiple=terminal_fcf_multiple,
        )
        terminal_share_price = terminal_share_price - np.maximum(non_property_net_debt, 0.0) / share_count[:, -1]
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
            maintenance_capex=maintenance_capex,
            growth_capex=growth_capex,
            share_count=share_count,
            total_gross_margin=total_gross_margin,
            operating_margin=operating_margin,
            dividends_per_share=dividends_per_share,
            terminal_pe=terminal_pe,
            terminal_fcf_multiple=terminal_fcf_multiple,
            regime_code=regime_code,
            shock_occurs=shock_occurs,
            accelerated_depreciation_occurs=lease_pressure_mask,
            terminal_share_price=terminal_share_price,
            ending_value_per_share=ending_value_per_share,
            cagr=cagr,
        )

    def sensitivity_variables(self) -> list[str]:
        return [
            "terminal_pe",
            "terminal_fcf_multiple",
            "gym_new_sites",
            "gym_revenue_per_site_growth",
            "gym_cash_margin",
            "gym_growth_capex",
            "gym_lease_liability",
            "gym_consumer_squeeze_probability",
        ]

    def regime_definitions(self) -> list[RegimeDefinition]:
        return [
            RegimeDefinition(
                key="expansion_compounding",
                label="Expansion compounding",
                description="New-site rollout stays strong, unit economics hold, and lease leverage remains controlled.",
                code=REGIME_SCARCITY,
            ),
            RegimeDefinition(
                key="steady_rollout",
                label="Steady rollout",
                description="Organic growth and site openings continue at a more normal pace.",
                code=REGIME_BALANCED,
            ),
            RegimeDefinition(
                key="lease_leverage_pressure",
                label="Lease leverage pressure",
                description="IFRS16 lease burden or non-property leverage weighs on equity value.",
                code=REGIME_OVERBUILD,
            ),
            RegimeDefinition(
                key="consumer_squeeze",
                label="Trade-down tailwind",
                description="Cost-of-living pressure modestly hits yield, but low-cost gyms benefit from migration from higher-cost formats.",
                code=REGIME_DISAPPOINTMENT,
            ),
        ]

    def default_editor_schema(self) -> dict[str, Any]:
        return {
            "common": ["market", "simulation", "valuation", "capital_return", "histogram"],
            "business_specific": ["business_model_inputs"],
        }


def _sample_growth_periods(
    periods: GrowthPeriods,
    simulation_count: int,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    return {
        "years_1_to_3": sample_distribution(periods.years_1_to_3, simulation_count, rng),
        "years_4_to_7": sample_distribution(periods.years_4_to_7, simulation_count, rng),
        "years_8_to_10": sample_distribution(periods.years_8_to_10, simulation_count, rng),
    }


def _growth_for_year(samples: dict[str, np.ndarray], year_number: int) -> np.ndarray:
    if year_number <= 3:
        return samples["years_1_to_3"]
    if year_number <= 7:
        return samples["years_4_to_7"]
    return samples["years_8_to_10"]
