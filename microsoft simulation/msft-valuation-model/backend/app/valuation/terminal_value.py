from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.model.assumptions import Scenario
from app.model.distributions import clamp, geometric_cagr, safe_divide, sample_distribution


@dataclass(frozen=True)
class TerminalMultiples:
    terminal_pe: np.ndarray
    terminal_fcf_multiple: np.ndarray
    terminal_price_to_book: np.ndarray | None = None
    terminal_dividend_yield: np.ndarray | None = None


def sample_terminal_multiples(
    scenario: Scenario,
    simulation_count: int,
    rng: np.random.Generator,
    *,
    minimum: float = 1.0,
) -> TerminalMultiples:
    terminal_price_to_book = None
    terminal_dividend_yield = None
    if scenario.valuation.terminal_price_to_book is not None:
        terminal_price_to_book = clamp(
            sample_distribution(scenario.valuation.terminal_price_to_book, simulation_count, rng),
            0.01,
            None,
        )
    if scenario.valuation.terminal_dividend_yield is not None:
        terminal_dividend_yield = clamp(
            sample_distribution(scenario.valuation.terminal_dividend_yield, simulation_count, rng),
            0.001,
            None,
        )

    return TerminalMultiples(
        terminal_pe=clamp(sample_distribution(scenario.valuation.terminal_pe, simulation_count, rng), minimum, None),
        terminal_fcf_multiple=clamp(
            sample_distribution(scenario.valuation.terminal_fcf_multiple, simulation_count, rng),
            minimum,
            None,
        ),
        terminal_price_to_book=terminal_price_to_book,
        terminal_dividend_yield=terminal_dividend_yield,
    )


def weighted_pe_fcf_terminal_share_price(
    *,
    scenario: Scenario,
    terminal_eps: np.ndarray,
    terminal_fcf: np.ndarray,
    terminal_share_count: np.ndarray,
    terminal_pe: np.ndarray,
    terminal_fcf_multiple: np.ndarray,
) -> np.ndarray:
    return weighted_terminal_share_price(
        scenario=scenario,
        terminal_eps=terminal_eps,
        terminal_fcf=terminal_fcf,
        terminal_share_count=terminal_share_count,
        terminal_pe=terminal_pe,
        terminal_fcf_multiple=terminal_fcf_multiple,
    )


def weighted_terminal_share_price(
    *,
    scenario: Scenario,
    terminal_eps: np.ndarray,
    terminal_fcf: np.ndarray,
    terminal_share_count: np.ndarray,
    terminal_pe: np.ndarray,
    terminal_fcf_multiple: np.ndarray,
    terminal_book_value: np.ndarray | None = None,
    terminal_price_to_book: np.ndarray | None = None,
    terminal_dividend_per_share: np.ndarray | None = None,
    terminal_dividend_yield: np.ndarray | None = None,
) -> np.ndarray:
    terminal_fcf_per_share = safe_divide(terminal_fcf, terminal_share_count)
    terminal_value_eps = terminal_eps * terminal_pe
    terminal_value_fcf = terminal_fcf_per_share * terminal_fcf_multiple
    terminal_share_price = (
        scenario.valuation.valuation_weight_eps * terminal_value_eps
        + scenario.valuation.valuation_weight_fcf * terminal_value_fcf
    )

    if scenario.valuation.valuation_weight_price_to_book:
        if terminal_book_value is None or terminal_price_to_book is None:
            raise ValueError("price-to-book valuation requires terminal book value and terminal P/B multiple")
        book_value_per_share = safe_divide(terminal_book_value, terminal_share_count)
        terminal_share_price += scenario.valuation.valuation_weight_price_to_book * (
            book_value_per_share * terminal_price_to_book
        )

    if scenario.valuation.valuation_weight_dividend_yield:
        if terminal_dividend_per_share is None or terminal_dividend_yield is None:
            raise ValueError("dividend-yield valuation requires terminal dividend per share and terminal yield")
        terminal_share_price += scenario.valuation.valuation_weight_dividend_yield * (
            terminal_dividend_per_share / terminal_dividend_yield
        )

    return terminal_share_price + scenario.valuation.net_cash_adjustment_bn / scenario.market.estimated_diluted_shares_bn


def total_return_cagr(
    *,
    terminal_share_price: np.ndarray,
    dividends_per_share: np.ndarray,
    current_share_price: float,
    horizon_years: int,
) -> tuple[np.ndarray, np.ndarray]:
    ending_value_per_share = terminal_share_price + dividends_per_share.sum(axis=1)
    cagr = geometric_cagr(ending_value_per_share, current_share_price, horizon_years)
    return ending_value_per_share, cagr
