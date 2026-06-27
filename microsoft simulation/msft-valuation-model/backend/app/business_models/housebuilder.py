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


class HousebuilderShockInputs(BaseModel):
    enabled: bool = True
    probability: DistributionSpec
    shock_year: DistributionSpec
    completions_decline: DistributionSpec
    asp_decline: DistributionSpec
    gross_margin_haircut: DistributionSpec
    land_write_down_probability_given_shock: DistributionSpec
    land_write_down_pct_book: DistributionSpec
    terminal_pb_haircut: DistributionSpec


class HousebuilderInputs(BaseModel):
    starting_completions: float
    starting_average_selling_price: float
    starting_book_value_bn: float
    starting_net_debt_bn: float = 0.0
    completions_growth: GrowthPeriods
    asp_growth: GrowthPeriods
    gross_margin: TerminalMarginSpec
    operating_cost_pct_revenue: DistributionSpec
    land_reinvestment_pct_revenue: DistributionSpec
    working_capital_pct_revenue_change: DistributionSpec
    tax_rate: DistributionSpec | None = None
    housing_downturn_shock: HousebuilderShockInputs | None = None


class HousebuilderModel:
    business_model_type = "housebuilder"

    def validate_inputs(self, scenario: Scenario) -> None:
        HousebuilderInputs.model_validate(scenario.business_model_inputs)

    def simulate(
        self,
        scenario: Scenario,
        rng: np.random.Generator,
        simulation_count: int,
    ) -> SimulationArrays:
        inputs = HousebuilderInputs.model_validate(scenario.business_model_inputs)
        horizon = scenario.simulation.horizon_years

        tax_spec = inputs.tax_rate or scenario.simulation.tax_rate
        tax_rate = clamp(sample_distribution(tax_spec, simulation_count, rng), 0.0, 0.5)
        operating_cost_pct = clamp(
            sample_distribution(inputs.operating_cost_pct_revenue, simulation_count, rng),
            0.0,
            0.5,
        )
        land_reinvestment_pct = clamp(
            sample_distribution(inputs.land_reinvestment_pct_revenue, simulation_count, rng),
            0.0,
            1.0,
        )
        working_capital_pct = clamp(
            sample_distribution(inputs.working_capital_pct_revenue_change, simulation_count, rng),
            0.0,
            2.0,
        )
        completions_growth = _sample_growth_periods(inputs.completions_growth, simulation_count, rng)
        asp_growth = _sample_growth_periods(inputs.asp_growth, simulation_count, rng)
        terminal_gross_margin = clamp(
            sample_distribution(inputs.gross_margin.terminal, simulation_count, rng),
            0.0,
            0.6,
        )
        gross_margin_path = interpolate_linear(inputs.gross_margin.start, terminal_gross_margin, horizon)
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
        terminal_price_to_book = terminal_multiples.terminal_price_to_book
        terminal_dividend_yield = terminal_multiples.terminal_dividend_yield

        shock = inputs.housing_downturn_shock
        if shock and shock.enabled:
            shock_probability = clamp(sample_distribution(shock.probability, simulation_count, rng), 0.0, 1.0)
            shock_occurs = rng.random(simulation_count) < shock_probability
            shock_year = np.clip(sample_distribution(shock.shock_year, simulation_count, rng).astype(int), 1, horizon)
            completions_decline = clamp(sample_distribution(shock.completions_decline, simulation_count, rng), 0.0, 0.95)
            asp_decline = clamp(sample_distribution(shock.asp_decline, simulation_count, rng), 0.0, 0.95)
            gross_margin_haircut = clamp(sample_distribution(shock.gross_margin_haircut, simulation_count, rng), 0.0, 0.6)
            write_down_probability = clamp(
                sample_distribution(shock.land_write_down_probability_given_shock, simulation_count, rng),
                0.0,
                1.0,
            )
            land_write_down_pct = clamp(sample_distribution(shock.land_write_down_pct_book, simulation_count, rng), 0.0, 0.9)
            terminal_pb_haircut = clamp(sample_distribution(shock.terminal_pb_haircut, simulation_count, rng), 0.0, 0.9)
        else:
            shock_occurs = np.zeros(simulation_count, dtype=bool)
            shock_year = np.full(simulation_count, horizon + 1, dtype=int)
            completions_decline = np.zeros(simulation_count, dtype=float)
            asp_decline = np.zeros(simulation_count, dtype=float)
            gross_margin_haircut = np.zeros(simulation_count, dtype=float)
            write_down_probability = np.zeros(simulation_count, dtype=float)
            land_write_down_pct = np.zeros(simulation_count, dtype=float)
            terminal_pb_haircut = np.zeros(simulation_count, dtype=float)

        land_write_down_occurs = shock_occurs & (rng.random(simulation_count) < write_down_probability)
        recovery_mask = (
            (~shock_occurs)
            & (completions_growth["years_1_to_3"] >= 0.035)
            & (asp_growth["years_1_to_3"] >= 0.025)
            & (terminal_gross_margin >= 0.22)
        )
        land_margin_stress_mask = shock_occurs & (
            land_write_down_occurs | (gross_margin_haircut >= 0.08) | (land_reinvestment_pct >= 0.18)
        )
        housing_downturn_mask = shock_occurs & ~land_margin_stress_mask
        regime_code = np.full(simulation_count, REGIME_BALANCED, dtype=int)
        regime_code[recovery_mask] = REGIME_SCARCITY
        regime_code[housing_downturn_mask] = REGIME_DISAPPOINTMENT
        regime_code[land_margin_stress_mask] = REGIME_OVERBUILD

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
        total_gross_margin = np.zeros((simulation_count, horizon), dtype=float)
        operating_margin = np.zeros((simulation_count, horizon), dtype=float)
        dividends_per_share = np.zeros((simulation_count, horizon), dtype=float)
        book_value = np.zeros((simulation_count, horizon), dtype=float)

        prior_completions = np.full(simulation_count, inputs.starting_completions, dtype=float)
        prior_asp = np.full(simulation_count, inputs.starting_average_selling_price, dtype=float)
        prior_revenue = prior_completions * prior_asp / 1_000_000_000.0
        prior_book_value = np.full(simulation_count, inputs.starting_book_value_bn, dtype=float)
        prior_share_count = np.full(simulation_count, scenario.market.estimated_diluted_shares_bn, dtype=float)
        current_normalized_pe = scenario.market.current_share_price / max(
            scenario.market.current_normalized_eps_ttm,
            0.01,
        )

        for year_index in range(horizon):
            year_number = year_index + 1
            post_shock_mask = shock_occurs & (year_number >= shock_year)
            shock_hits_this_year = shock_occurs & (year_number == shock_year)
            years_since_shock = np.maximum(year_number - shock_year, 0)
            margin_shock_intensity = np.where(
                post_shock_mask,
                np.maximum(1.0 - years_since_shock / 3.0, 0.0),
                0.0,
            )
            completion_growth_rate = _growth_for_year(completions_growth, year_number)
            asp_growth_rate = _growth_for_year(asp_growth, year_number)

            completions = np.maximum(prior_completions * (1.0 + completion_growth_rate), 0.0)
            asp = np.maximum(prior_asp * (1.0 + asp_growth_rate), 0.0)
            completions = np.where(shock_hits_this_year, completions * (1.0 - completions_decline), completions)
            asp = np.where(shock_hits_this_year, asp * (1.0 - asp_decline), asp)

            revenue[:, year_index] = completions * asp / 1_000_000_000.0
            incremental_revenue = np.maximum(revenue[:, year_index] - prior_revenue, 0.0)
            gross_margin = clamp(
                gross_margin_path[:, year_index] - gross_margin_haircut * margin_shock_intensity,
                0.0,
                0.6,
            )
            total_gross_margin[:, year_index] = gross_margin
            gross_profit[:, year_index] = revenue[:, year_index] * gross_margin
            operating_income[:, year_index] = gross_profit[:, year_index] - revenue[:, year_index] * operating_cost_pct
            operating_margin[:, year_index] = safe_divide(operating_income[:, year_index], revenue[:, year_index])
            tax = np.maximum(operating_income[:, year_index], 0.0) * tax_rate
            net_income[:, year_index] = operating_income[:, year_index] - tax

            maintenance_investment[:, year_index] = revenue[:, year_index] * land_reinvestment_pct
            growth_investment[:, year_index] = incremental_revenue * working_capital_pct
            total_capex[:, year_index] = maintenance_investment[:, year_index] + growth_investment[:, year_index]
            # Land replenishment is inventory/book recycling for housebuilders, not a permanent
            # owner-cash deduction. Keep it visible in capex diagnostics, but use an owner FCF
            # view for dividends, buybacks, and terminal FCF/share.
            fcf[:, year_index] = net_income[:, year_index] - growth_investment[:, year_index]

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

            write_down = np.where(shock_hits_this_year & land_write_down_occurs, prior_book_value * land_write_down_pct, 0.0)
            dividends_paid = capital_return.dividends_per_share * prior_share_count
            book_value[:, year_index] = np.maximum(prior_book_value + net_income[:, year_index] - dividends_paid - write_down, 0.0)

            prior_completions = completions
            prior_asp = asp
            prior_revenue = revenue[:, year_index]
            prior_book_value = book_value[:, year_index]
            prior_share_count = share_count[:, year_index]

        if terminal_price_to_book is not None:
            terminal_price_to_book = np.where(
                shock_occurs,
                terminal_price_to_book * (1.0 - terminal_pb_haircut),
                terminal_price_to_book,
            )

        terminal_share_price = weighted_terminal_share_price(
            scenario=scenario,
            terminal_eps=eps[:, -1],
            terminal_fcf=fcf[:, -1],
            terminal_share_count=share_count[:, -1],
            terminal_pe=terminal_pe,
            terminal_fcf_multiple=terminal_fcf_multiple,
            terminal_book_value=book_value[:, -1],
            terminal_price_to_book=terminal_price_to_book,
            terminal_dividend_per_share=dividends_per_share[:, -1],
            terminal_dividend_yield=terminal_dividend_yield,
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
            total_gross_margin=total_gross_margin,
            operating_margin=operating_margin,
            dividends_per_share=dividends_per_share,
            terminal_pe=terminal_pe,
            terminal_fcf_multiple=terminal_fcf_multiple,
            regime_code=regime_code,
            shock_occurs=shock_occurs,
            accelerated_depreciation_occurs=land_write_down_occurs,
            terminal_share_price=terminal_share_price,
            ending_value_per_share=ending_value_per_share,
            cagr=cagr,
        )

    def sensitivity_variables(self) -> list[str]:
        return [
            "terminal_pe",
            "terminal_price_to_book",
            "terminal_dividend_yield",
            "completions_growth",
            "average_selling_price_growth",
            "gross_margin",
            "land_reinvestment_pct_revenue",
            "housing_downturn_probability",
        ]

    def regime_definitions(self) -> list[RegimeDefinition]:
        return [
            RegimeDefinition(
                key="recovery",
                label="Recovery / volume growth",
                description="No downturn shock, with stronger completions, ASP growth, and resilient terminal margins.",
                code=REGIME_SCARCITY,
            ),
            RegimeDefinition(
                key="steady_cycle",
                label="Steady housing cycle",
                description="No downturn shock, with more normal volume, pricing, margin, and land cash absorption.",
                code=REGIME_BALANCED,
            ),
            RegimeDefinition(
                key="housing_downturn",
                label="Housing downturn",
                description="A cyclical shock hits completions, ASP, and gross margin.",
                code=REGIME_DISAPPOINTMENT,
            ),
            RegimeDefinition(
                key="land_margin_stress",
                label="Land / margin stress",
                description="Downturn conditions combine with land write-down risk, higher reinvestment, or deeper margin pressure.",
                code=REGIME_OVERBUILD,
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
