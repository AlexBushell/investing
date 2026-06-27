import json
from pathlib import Path

import numpy as np

from app.model.assumptions import Scenario
from app.valuation.capital_returns import CapitalReturnPolicy, apply_capital_returns_for_year
from app.valuation.terminal_value import (
    total_return_cagr,
    weighted_pe_fcf_terminal_share_price,
    weighted_terminal_share_price,
)


GENERIC_SCENARIO_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "generic_default.json"


def load_generic_scenario() -> Scenario:
    return Scenario.model_validate(json.loads(GENERIC_SCENARIO_PATH.read_text(encoding="utf-8")))


def test_capital_returns_apply_dividends_and_buyback_limits() -> None:
    policy = CapitalReturnPolicy(
        dividend_payout_ratio=np.array([0.25]),
        buyback_pct_of_post_dividend_fcf=np.array([1.0]),
        buyback_price_premium_to_intrinsic=np.array([0.0]),
        max_annual_share_reduction=np.array([0.10]),
    )

    result = apply_capital_returns_for_year(
        net_income=np.array([100.0]),
        free_cash_flow=np.array([90.0]),
        prior_share_count=np.array([10.0]),
        estimated_share_price=np.array([5.0]),
        policy=policy,
    )

    assert result.dividends_paid[0] == 25.0
    assert result.dividends_per_share[0] == 2.5
    assert result.buyback_cash[0] == 65.0
    assert result.shares_reduced[0] == 1.0
    assert result.ending_share_count[0] == 9.0


def test_weighted_pe_fcf_terminal_share_price_uses_scenario_weights() -> None:
    scenario = load_generic_scenario()
    scenario.valuation.valuation_weight_eps = 0.6
    scenario.valuation.valuation_weight_fcf = 0.4
    scenario.valuation.net_cash_adjustment_bn = 0.1

    terminal_price = weighted_pe_fcf_terminal_share_price(
        scenario=scenario,
        terminal_eps=np.array([2.0]),
        terminal_fcf=np.array([15.0]),
        terminal_share_count=np.array([10.0]),
        terminal_pe=np.array([12.0]),
        terminal_fcf_multiple=np.array([8.0]),
    )

    assert terminal_price[0] == 0.6 * 24.0 + 0.4 * 12.0 + 1.0


def test_total_return_cagr_includes_cumulative_dividends() -> None:
    ending_value, cagr = total_return_cagr(
        terminal_share_price=np.array([120.0]),
        dividends_per_share=np.array([[2.0, 3.0, 5.0]]),
        current_share_price=100.0,
        horizon_years=3,
    )

    assert ending_value[0] == 130.0
    assert np.isclose(cagr[0], 1.3 ** (1.0 / 3.0) - 1.0)


def test_weighted_terminal_share_price_supports_book_and_dividend_yield() -> None:
    scenario = load_generic_scenario()
    scenario.valuation.valuation_weight_eps = 0.0
    scenario.valuation.valuation_weight_fcf = 0.0
    scenario.valuation.valuation_weight_price_to_book = 0.75
    scenario.valuation.valuation_weight_dividend_yield = 0.25

    terminal_price = weighted_terminal_share_price(
        scenario=scenario,
        terminal_eps=np.array([0.0]),
        terminal_fcf=np.array([0.0]),
        terminal_share_count=np.array([10.0]),
        terminal_pe=np.array([10.0]),
        terminal_fcf_multiple=np.array([10.0]),
        terminal_book_value=np.array([100.0]),
        terminal_price_to_book=np.array([1.2]),
        terminal_dividend_per_share=np.array([0.6]),
        terminal_dividend_yield=np.array([0.05]),
    )

    assert terminal_price[0] == 0.75 * 12.0 + 0.25 * 12.0
