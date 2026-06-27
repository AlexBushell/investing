from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.model.assumptions import Scenario
from app.model.distributions import clamp, safe_divide, sample_distribution


@dataclass(frozen=True)
class CapitalReturnPolicy:
    dividend_payout_ratio: np.ndarray
    buyback_pct_of_post_dividend_fcf: np.ndarray
    buyback_price_premium_to_intrinsic: np.ndarray
    max_annual_share_reduction: np.ndarray


@dataclass(frozen=True)
class CapitalReturnResult:
    dividends_paid: np.ndarray
    dividends_per_share: np.ndarray
    buyback_cash: np.ndarray
    shares_reduced: np.ndarray
    ending_share_count: np.ndarray


def sample_capital_return_policy(
    scenario: Scenario,
    simulation_count: int,
    rng: np.random.Generator,
    *,
    dividend_payout_cap: float = 1.0,
    max_share_reduction_cap: float = 0.25,
) -> CapitalReturnPolicy:
    return CapitalReturnPolicy(
        dividend_payout_ratio=clamp(
            sample_distribution(scenario.capital_return.dividend_payout_ratio, simulation_count, rng),
            0.0,
            dividend_payout_cap,
        ),
        buyback_pct_of_post_dividend_fcf=clamp(
            sample_distribution(scenario.capital_return.buyback_pct_of_post_dividend_fcf, simulation_count, rng),
            0.0,
            1.0,
        ),
        buyback_price_premium_to_intrinsic=sample_distribution(
            scenario.capital_return.buyback_price_premium_to_intrinsic,
            simulation_count,
            rng,
        ),
        max_annual_share_reduction=clamp(
            sample_distribution(scenario.capital_return.max_annual_share_reduction, simulation_count, rng),
            0.0,
            max_share_reduction_cap,
        ),
    )


def apply_capital_returns_for_year(
    *,
    net_income: np.ndarray,
    free_cash_flow: np.ndarray,
    prior_share_count: np.ndarray,
    estimated_share_price: np.ndarray,
    policy: CapitalReturnPolicy,
) -> CapitalReturnResult:
    dividends_paid = np.maximum(net_income, 0.0) * policy.dividend_payout_ratio
    dividends_per_share = safe_divide(dividends_paid, prior_share_count)

    available_post_dividend_fcf = np.maximum(free_cash_flow - dividends_paid, 0.0)
    buyback_cash = available_post_dividend_fcf * policy.buyback_pct_of_post_dividend_fcf
    buyback_price = np.maximum(
        estimated_share_price * (1.0 + policy.buyback_price_premium_to_intrinsic),
        1.0,
    )
    shares_reduced = np.minimum(
        buyback_cash / buyback_price,
        prior_share_count * policy.max_annual_share_reduction,
    )
    ending_share_count = np.maximum(
        prior_share_count - shares_reduced,
        prior_share_count * (1.0 - policy.max_annual_share_reduction),
    )

    return CapitalReturnResult(
        dividends_paid=dividends_paid,
        dividends_per_share=dividends_per_share,
        buyback_cash=buyback_cash,
        shares_reduced=shares_reduced,
        ending_share_count=ending_share_count,
    )

