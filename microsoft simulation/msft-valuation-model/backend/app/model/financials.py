from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.model.assumptions import Scenario
from app.model.distributions import clamp, interpolate_linear, safe_divide, sample_distribution
from app.valuation.capital_returns import apply_capital_returns_for_year, sample_capital_return_policy
from app.valuation.terminal_value import (
    sample_terminal_multiples,
    total_return_cagr,
    weighted_pe_fcf_terminal_share_price,
)


AI_LINE_KEYWORDS = ("AI Apps", "Azure AI")
REGIME_SCARCITY = 0
REGIME_BALANCED = 1
REGIME_OVERBUILD = 2
REGIME_DISAPPOINTMENT = 3


@dataclass
class SimulationArrays:
    revenue: np.ndarray
    gross_profit: np.ndarray
    operating_income: np.ndarray
    net_income: np.ndarray
    eps: np.ndarray
    depreciation: np.ndarray
    fcf: np.ndarray
    total_capex: np.ndarray
    maintenance_capex: np.ndarray
    growth_capex: np.ndarray
    share_count: np.ndarray
    total_gross_margin: np.ndarray
    operating_margin: np.ndarray
    dividends_per_share: np.ndarray
    terminal_pe: np.ndarray
    terminal_fcf_multiple: np.ndarray
    regime_code: np.ndarray
    shock_occurs: np.ndarray
    accelerated_depreciation_occurs: np.ndarray
    terminal_share_price: np.ndarray
    ending_value_per_share: np.ndarray
    cagr: np.ndarray


def simulate_financials(
    scenario: Scenario,
    simulation_count: int,
    rng: np.random.Generator,
) -> SimulationArrays:
    horizon = scenario.simulation.horizon_years
    lines = scenario.revenue_lines
    line_count = len(lines)
    revenue_by_line = np.zeros((simulation_count, horizon, line_count), dtype=float)
    gross_profit_by_line = np.zeros((simulation_count, horizon, line_count), dtype=float)

    tax_rate = sample_distribution(scenario.simulation.tax_rate, simulation_count, rng)
    tax_rate = clamp(tax_rate, 0.0, 0.5)

    short_share = sample_distribution(scenario.capex.short_lived_asset_share, simulation_count, rng)
    short_share = clamp(short_share, 0.05, 0.95)
    long_share = 1.0 - short_share

    gpu_life = clamp(
        sample_distribution(scenario.capex.gpu_economic_life_years, simulation_count, rng), 1.0, None
    )
    datacenter_life = clamp(
        sample_distribution(scenario.capex.datacenter_economic_life_years, simulation_count, rng), 2.0, None
    )
    component_cost_change = sample_distribution(
        scenario.capex.component_cost_change_per_year, simulation_count, rng
    )

    ai_extra_opex = clamp(
        sample_distribution(scenario.opex.ai_extra_opex_pct_of_ai_revenue, simulation_count, rng), 0.0, 0.5
    )
    opex_terminal = clamp(
        sample_distribution(scenario.opex.rd_and_sga_pct_of_revenue.terminal, simulation_count, rng), 0.05, 0.5
    )
    opex_path = interpolate_linear(scenario.opex.rd_and_sga_pct_of_revenue.start, opex_terminal, horizon)

    capital_return_policy = sample_capital_return_policy(
        scenario,
        simulation_count,
        rng,
        dividend_payout_cap=0.8,
        max_share_reduction_cap=0.05,
    )
    terminal_multiples = sample_terminal_multiples(scenario, simulation_count, rng, minimum=1.0)
    terminal_pe = terminal_multiples.terminal_pe
    terminal_fcf_multiple = terminal_multiples.terminal_fcf_multiple

    if scenario.shock.enable_price_crash:
        shock_probability = clamp(
            sample_distribution(scenario.shock.shock_probability, simulation_count, rng), 0.0, 1.0
        )
        shock_occurs = rng.random(simulation_count) < shock_probability
        shock_year = sample_distribution(scenario.shock.shock_year, simulation_count, rng).astype(int)
        shock_year = np.clip(shock_year, 1, horizon)
        ai_price_decline = clamp(
            sample_distribution(scenario.shock.ai_price_decline, simulation_count, rng), 0.0, 0.95
        )
        utilisation_decline = clamp(
            sample_distribution(scenario.shock.utilisation_decline, simulation_count, rng), 0.0, 0.95
        )
        ai_growth_haircut = clamp(
            sample_distribution(scenario.shock.ai_growth_haircut_after_shock, simulation_count, rng), 0.0, 0.95
        )
        ai_margin_haircut = clamp(
            sample_distribution(scenario.shock.ai_margin_haircut_after_shock, simulation_count, rng), 0.0, 0.95
        )
        future_growth_capex_reduction = clamp(
            sample_distribution(scenario.shock.future_growth_capex_reduction_after_shock, simulation_count, rng),
            0.0,
            0.95,
        )
        accelerated_depreciation_probability = clamp(
            sample_distribution(
                scenario.shock.accelerated_depreciation_probability_given_shock, simulation_count, rng
            ),
            0.0,
            1.0,
        )
        accelerated_depreciation_pct = clamp(
            sample_distribution(
                scenario.shock.accelerated_depreciation_pct_of_short_lived_asset_base, simulation_count, rng
            ),
            0.0,
            0.95,
        )
        terminal_multiple_haircut = clamp(
            sample_distribution(scenario.shock.terminal_multiple_haircut_given_shock, simulation_count, rng), 0.0, 0.95
        )
    else:
        shock_occurs = np.zeros(simulation_count, dtype=bool)
        shock_year = np.full(simulation_count, horizon + 1, dtype=int)
        ai_price_decline = np.zeros(simulation_count, dtype=float)
        utilisation_decline = np.zeros(simulation_count, dtype=float)
        ai_growth_haircut = np.zeros(simulation_count, dtype=float)
        ai_margin_haircut = np.zeros(simulation_count, dtype=float)
        future_growth_capex_reduction = np.zeros(simulation_count, dtype=float)
        accelerated_depreciation_probability = np.zeros(simulation_count, dtype=float)
        accelerated_depreciation_pct = np.zeros(simulation_count, dtype=float)
        terminal_multiple_haircut = np.zeros(simulation_count, dtype=float)

    accelerated_depreciation_occurs = shock_occurs & (
        rng.random(simulation_count) < accelerated_depreciation_probability
    )

    current_normalized_pe = scenario.market.current_share_price / max(
        scenario.market.current_normalized_eps_ttm, 0.01
    )
    share_count = np.full((simulation_count, horizon), scenario.market.estimated_diluted_shares_bn, dtype=float)
    dividends_per_share = np.zeros((simulation_count, horizon), dtype=float)

    total_revenue = np.zeros((simulation_count, horizon), dtype=float)
    total_gross_profit = np.zeros((simulation_count, horizon), dtype=float)
    operating_income = np.zeros((simulation_count, horizon), dtype=float)
    net_income = np.zeros((simulation_count, horizon), dtype=float)
    eps = np.zeros((simulation_count, horizon), dtype=float)
    depreciation = np.zeros((simulation_count, horizon), dtype=float)
    fcf = np.zeros((simulation_count, horizon), dtype=float)
    total_capex = np.zeros((simulation_count, horizon), dtype=float)
    maintenance_capex = np.zeros((simulation_count, horizon), dtype=float)
    growth_capex = np.zeros((simulation_count, horizon), dtype=float)
    total_gross_margin = np.zeros((simulation_count, horizon), dtype=float)
    operating_margin = np.zeros((simulation_count, horizon), dtype=float)

    initial_short_asset_base = (
        scenario.base_financials.fy2025_ppe_additions_bn * short_share * gpu_life
    )
    initial_long_asset_base = (
        scenario.base_financials.fy2025_ppe_additions_bn * long_share * datacenter_life
    )
    short_asset_base = initial_short_asset_base.copy()
    long_asset_base = initial_long_asset_base.copy()

    overlays = {
        0: sample_distribution(scenario.capex.initial_capex_overlay_bn.year_1, simulation_count, rng),
        1: sample_distribution(scenario.capex.initial_capex_overlay_bn.year_2, simulation_count, rng),
        2: sample_distribution(scenario.capex.initial_capex_overlay_bn.year_3, simulation_count, rng),
    }

    prior_line_revenue = np.array([line.starting_revenue_bn for line in lines], dtype=float)
    prior_line_revenue = np.broadcast_to(prior_line_revenue, (simulation_count, line_count)).copy()

    growth_samples = []
    margin_terminal_samples = []
    maintenance_samples = []
    growth_capex_samples = []
    ai_line_mask = np.array([any(key in line.name for key in AI_LINE_KEYWORDS) for line in lines], dtype=bool)

    for line in lines:
        growth_samples.append(
            {
                "years_1_to_3": sample_distribution(line.growth.years_1_to_3, simulation_count, rng),
                "years_4_to_7": sample_distribution(line.growth.years_4_to_7, simulation_count, rng),
                "years_8_to_10": sample_distribution(line.growth.years_8_to_10, simulation_count, rng),
            }
        )
        margin_terminal_samples.append(
            clamp(sample_distribution(line.gross_margin.terminal, simulation_count, rng), 0.05, 0.95)
        )
        maintenance_samples.append(
            clamp(sample_distribution(line.capex_intensity.maintenance_pct_of_revenue, simulation_count, rng), 0.0, 1.0)
        )
        growth_capex_samples.append(
            clamp(
                sample_distribution(line.capex_intensity.growth_pct_of_incremental_revenue, simulation_count, rng),
                0.0,
                5.0,
            )
        )

    margin_paths = np.stack(
        [interpolate_linear(lines[i].gross_margin.start, margin_terminal_samples[i], horizon) for i in range(line_count)],
        axis=2,
    )

    ai_line_indices = np.where(ai_line_mask)[0]
    if ai_line_indices.size:
        ai_growth_signal = np.vstack(
            [growth_samples[index]["years_1_to_3"] for index in ai_line_indices]
        ).mean(axis=0)
        ai_terminal_margin_signal = np.vstack(
            [margin_terminal_samples[index] for index in ai_line_indices]
        ).mean(axis=0)
    else:
        ai_growth_signal = np.zeros(simulation_count, dtype=float)
        ai_terminal_margin_signal = np.zeros(simulation_count, dtype=float)

    shock_severity = 0.45 * ai_price_decline + 0.35 * utilisation_decline + 0.20 * ai_growth_haircut
    regime_code = np.full(simulation_count, REGIME_BALANCED, dtype=int)
    scarcity_mask = (~shock_occurs) & (ai_growth_signal >= 0.42) & (ai_terminal_margin_signal >= 0.50)
    overbuild_mask = shock_occurs & ((shock_severity >= 0.24) | (ai_growth_signal >= 0.35))
    disappointment_mask = (
        ((~shock_occurs) & (ai_growth_signal < 0.28) & (ai_terminal_margin_signal < 0.50))
        | (shock_occurs & ~overbuild_mask)
    )
    regime_code[scarcity_mask] = REGIME_SCARCITY
    regime_code[overbuild_mask] = REGIME_OVERBUILD
    regime_code[disappointment_mask] = REGIME_DISAPPOINTMENT

    ai_growth_multiplier_pre = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [1.12, 1.08, 0.82],
        default=1.0,
    )
    ai_growth_multiplier_post = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [1.03, 0.72, 0.78],
        default=1.0,
    )
    ai_margin_bonus_pre = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [0.03, -0.01, -0.03],
        default=0.0,
    )
    ai_margin_bonus_post = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [0.02, -0.09, -0.06],
        default=0.0,
    )
    growth_capex_regime_pre = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [1.15, 1.20, 0.85],
        default=1.0,
    )
    growth_capex_regime_post = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [1.05, 0.60, 0.75],
        default=1.0,
    )
    terminal_pe_regime_adjustment = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [3.0, -3.0, -5.0],
        default=0.0,
    )
    terminal_fcf_regime_adjustment = np.select(
        [
            regime_code == REGIME_SCARCITY,
            regime_code == REGIME_OVERBUILD,
            regime_code == REGIME_DISAPPOINTMENT,
        ],
        [2.5, -2.5, -4.0],
        default=0.0,
    )

    for year_index in range(horizon):
        year_number = year_index + 1
        post_shock_mask = shock_occurs & (year_number >= shock_year)
        shock_hits_this_year = shock_occurs & (year_number == shock_year)
        cost_factor = np.power(1.0 + component_cost_change, year_index)

        for line_index, line in enumerate(lines):
            if year_number <= 3:
                base_growth = growth_samples[line_index]["years_1_to_3"]
            elif year_number <= 7:
                base_growth = growth_samples[line_index]["years_4_to_7"]
            else:
                base_growth = growth_samples[line_index]["years_8_to_10"]

            effective_growth = base_growth.copy()
            if ai_line_mask[line_index]:
                effective_growth = effective_growth * ai_growth_multiplier_pre
                effective_growth = np.where(
                    post_shock_mask,
                    effective_growth * (1.0 - ai_growth_haircut) * ai_growth_multiplier_post,
                    effective_growth,
                )

            current_revenue = prior_line_revenue[:, line_index] * (1.0 + effective_growth)
            current_revenue = np.maximum(current_revenue, 0.0)

            if ai_line_mask[line_index]:
                current_revenue = np.where(
                    shock_hits_this_year,
                    current_revenue * (1.0 - ai_price_decline),
                    current_revenue,
                )

            revenue_by_line[:, year_index, line_index] = current_revenue

            gross_margin = margin_paths[:, year_index, line_index]
            if ai_line_mask[line_index]:
                gross_margin = gross_margin + ai_margin_bonus_pre
                effective_margin_haircut = ai_margin_haircut + 0.25 * utilisation_decline
                gross_margin = np.where(
                    post_shock_mask,
                    gross_margin - effective_margin_haircut + ai_margin_bonus_post,
                    gross_margin,
                )

            gross_margin = clamp(gross_margin, 0.05, 0.95)
            gross_profit_by_line[:, year_index, line_index] = current_revenue * gross_margin

            prior_line_revenue[:, line_index] = current_revenue

        total_revenue[:, year_index] = revenue_by_line[:, year_index, :].sum(axis=1)
        total_gross_profit[:, year_index] = gross_profit_by_line[:, year_index, :].sum(axis=1)
        total_gross_margin[:, year_index] = safe_divide(total_gross_profit[:, year_index], total_revenue[:, year_index])

        ai_revenue = revenue_by_line[:, year_index, ai_line_mask].sum(axis=1)
        current_opex_pct = opex_path[:, year_index]
        opex = total_revenue[:, year_index] * current_opex_pct + ai_revenue * ai_extra_opex
        operating_income[:, year_index] = total_gross_profit[:, year_index] - opex
        operating_margin[:, year_index] = safe_divide(operating_income[:, year_index], total_revenue[:, year_index])

        line_growth_capex = np.zeros(simulation_count, dtype=float)
        for line_index in range(line_count):
            line_revenue = revenue_by_line[:, year_index, line_index]

            previous_revenue = revenue_by_line[:, year_index - 1, line_index] if year_index > 0 else np.full(
                simulation_count, lines[line_index].starting_revenue_bn, dtype=float
            )
            incremental_revenue = np.maximum(line_revenue - previous_revenue, 0.0)
            line_growth_capex += incremental_revenue * growth_capex_samples[line_index]

        short_replacement = short_asset_base / gpu_life
        long_replacement = long_asset_base / datacenter_life
        asset_base_replacement = (short_replacement + long_replacement) * cost_factor
        calculated_maintenance_capex = asset_base_replacement

        calculated_growth_capex = line_growth_capex * cost_factor * growth_capex_regime_pre
        calculated_growth_capex = np.where(
            post_shock_mask,
            calculated_growth_capex * (1.0 - future_growth_capex_reduction) * growth_capex_regime_post,
            calculated_growth_capex,
        )
        growth_capex[:, year_index] = calculated_growth_capex

        overlay = overlays.get(year_index, np.zeros(simulation_count, dtype=float))
        if year_index in overlays:
            total_capex[:, year_index] = overlay
            maintenance_capex[:, year_index] = np.minimum(calculated_maintenance_capex, total_capex[:, year_index])
            growth_capex[:, year_index] = np.maximum(
                total_capex[:, year_index] - maintenance_capex[:, year_index], 0.0
            )
        else:
            maintenance_capex[:, year_index] = calculated_maintenance_capex
            total_capex[:, year_index] = maintenance_capex[:, year_index] + growth_capex[:, year_index]

        short_lived_depreciation = short_asset_base / gpu_life
        long_lived_depreciation = long_asset_base / datacenter_life
        base_depreciation = short_lived_depreciation + long_lived_depreciation
        depreciation_shock_charge = np.where(
            accelerated_depreciation_occurs & (year_number == shock_year),
            short_asset_base * accelerated_depreciation_pct,
            0.0,
        )
        depreciation[:, year_index] = base_depreciation + depreciation_shock_charge

        tax = np.maximum(operating_income[:, year_index], 0.0) * tax_rate
        net_income_before_shock = operating_income[:, year_index] - tax
        net_income[:, year_index] = net_income_before_shock - depreciation_shock_charge * (1.0 - tax_rate)

        operating_cash_flow = net_income[:, year_index] + depreciation[:, year_index]
        fcf[:, year_index] = operating_cash_flow - total_capex[:, year_index]

        prior_share_count = share_count[:, year_index - 1] if year_index > 0 else share_count[:, 0].copy()
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
        next_share_count = capital_return.ending_share_count
        share_count[:, year_index] = next_share_count

        eps[:, year_index] = safe_divide(net_income[:, year_index], next_share_count)

        new_short_capex = total_capex[:, year_index] * short_share
        new_long_capex = total_capex[:, year_index] * long_share
        short_asset_base = np.maximum(short_asset_base + new_short_capex - short_lived_depreciation - depreciation_shock_charge, 0.0)
        long_asset_base = np.maximum(long_asset_base + new_long_capex - long_lived_depreciation, 0.0)

    total_starting_revenue = float(sum(line.starting_revenue_bn for line in lines))
    realized_revenue_cagr = np.power(
        np.maximum(total_revenue[:, -1] / max(total_starting_revenue, 1e-9), 1e-12),
        1.0 / horizon,
    ) - 1.0
    terminal_capex_intensity = total_capex[:, -1] / np.maximum(total_revenue[:, -1], 1e-9)
    terminal_fcf_margin = fcf[:, -1] / np.maximum(total_revenue[:, -1], 1e-9)

    terminal_pe = (
        terminal_pe
        + terminal_pe_regime_adjustment
        + 18.0 * (realized_revenue_cagr - 0.08)
        + 10.0 * (terminal_fcf_margin - 0.18)
        - 12.0 * (terminal_capex_intensity - 0.14)
    )
    terminal_fcf_multiple = (
        terminal_fcf_multiple
        + terminal_fcf_regime_adjustment
        + 14.0 * (realized_revenue_cagr - 0.08)
        + 12.0 * (terminal_fcf_margin - 0.18)
        - 10.0 * (terminal_capex_intensity - 0.14)
    )

    terminal_pe = np.where(shock_occurs, terminal_pe * (1.0 - terminal_multiple_haircut), terminal_pe)
    terminal_fcf_multiple = np.where(
        shock_occurs, terminal_fcf_multiple * (1.0 - terminal_multiple_haircut), terminal_fcf_multiple
    )
    terminal_pe = np.clip(terminal_pe, 5.0, 40.0)
    terminal_fcf_multiple = np.clip(terminal_fcf_multiple, 5.0, 40.0)

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
        revenue=total_revenue,
        gross_profit=total_gross_profit,
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
        accelerated_depreciation_occurs=accelerated_depreciation_occurs,
        terminal_share_price=terminal_share_price,
        ending_value_per_share=ending_value_per_share,
        cagr=cagr,
    )
