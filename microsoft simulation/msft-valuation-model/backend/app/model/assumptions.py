from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


DistributionType = Literal["pert", "fixed", "pert_integer", "derived"]
RegimeFilter = str


class DistributionSpec(BaseModel):
    type: DistributionType
    min: float | None = None
    mode: float | None = None
    max: float | None = None
    value: float | None = None
    formula: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "DistributionSpec":
        if self.type == "fixed":
            if self.value is None:
                if self.mode is None:
                    raise ValueError("fixed distribution requires value or mode")
                self.value = self.mode
        elif self.type in {"pert", "pert_integer"}:
            if self.min is None or self.mode is None or self.max is None:
                raise ValueError(f"{self.type} distribution requires min/mode/max")
            if not (self.min <= self.mode <= self.max):
                raise ValueError("distribution requires min <= mode <= max")
        return self


class TerminalMarginSpec(BaseModel):
    start: float
    terminal: DistributionSpec


class CapexIntensitySpec(BaseModel):
    maintenance_pct_of_revenue: DistributionSpec
    growth_pct_of_incremental_revenue: DistributionSpec


class GrowthPeriods(BaseModel):
    years_1_to_3: DistributionSpec
    years_4_to_7: DistributionSpec
    years_8_to_10: DistributionSpec


class RevenueLine(BaseModel):
    name: str
    starting_revenue_bn: float
    description: str | None = None
    growth: GrowthPeriods
    gross_margin: TerminalMarginSpec
    capex_intensity: CapexIntensitySpec


class OpexSpec(BaseModel):
    rd_and_sga_pct_of_revenue: TerminalMarginSpec
    ai_extra_opex_pct_of_ai_revenue: DistributionSpec


class CapexOverlay(BaseModel):
    year_1: DistributionSpec
    year_2: DistributionSpec
    year_3: DistributionSpec


class CapexSpec(BaseModel):
    short_lived_asset_share: DistributionSpec
    long_lived_asset_share: DistributionSpec
    gpu_economic_life_years: DistributionSpec
    datacenter_economic_life_years: DistributionSpec
    component_cost_change_per_year: DistributionSpec
    initial_capex_overlay_bn: CapexOverlay


class ShockSpec(BaseModel):
    enable_price_crash: bool = True
    shock_probability: DistributionSpec
    shock_year: DistributionSpec
    ai_price_decline: DistributionSpec
    utilisation_decline: DistributionSpec
    ai_growth_haircut_after_shock: DistributionSpec
    ai_margin_haircut_after_shock: DistributionSpec
    future_growth_capex_reduction_after_shock: DistributionSpec
    accelerated_depreciation_probability_given_shock: DistributionSpec
    accelerated_depreciation_pct_of_short_lived_asset_base: DistributionSpec
    terminal_multiple_haircut_given_shock: DistributionSpec


class CapitalReturnSpec(BaseModel):
    dividend_payout_ratio: DistributionSpec
    buyback_pct_of_post_dividend_fcf: DistributionSpec
    buyback_price_premium_to_intrinsic: DistributionSpec
    minimum_cash_buffer_bn: float
    max_annual_share_reduction: DistributionSpec


class ValuationSpec(BaseModel):
    terminal_pe: DistributionSpec
    terminal_fcf_multiple: DistributionSpec
    terminal_price_to_book: DistributionSpec | None = None
    terminal_dividend_yield: DistributionSpec | None = None
    valuation_weight_eps: float
    valuation_weight_fcf: float
    valuation_weight_price_to_book: float = 0.0
    valuation_weight_dividend_yield: float = 0.0
    net_cash_adjustment_bn: float = 0.0

    @model_validator(mode="after")
    def validate_weights(self) -> "ValuationSpec":
        total = (
            self.valuation_weight_eps
            + self.valuation_weight_fcf
            + self.valuation_weight_price_to_book
            + self.valuation_weight_dividend_yield
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError("valuation weights must sum to 1.0")
        if self.valuation_weight_price_to_book > 0 and self.terminal_price_to_book is None:
            raise ValueError("price-to-book valuation requires terminal_price_to_book")
        if self.valuation_weight_dividend_yield > 0 and self.terminal_dividend_yield is None:
            raise ValueError("dividend-yield valuation requires terminal_dividend_yield")
        return self


class SimulationSpec(BaseModel):
    horizon_years: int = Field(ge=1, le=50)
    simulation_count: int = Field(ge=100, le=200000)
    random_seed: int | None = None
    target_cagr: float
    tax_rate: DistributionSpec


class BaseFinancials(BaseModel):
    fy2025_revenue_bn: float
    fy2025_operating_income_bn: float
    fy2025_net_income_bn: float
    fy2025_eps: float
    fy2025_ppe_additions_bn: float
    fy2025_depreciation_bn: float
    fy2025_cloud_gross_margin_pct: float
    fy2026_q3_revenue_bn: float
    fy2026_q3_eps: float
    fy2026_q3_capex_bn: float
    fy2026_q3_cash_paid_for_ppe_bn: float
    fy2026_q3_fcf_bn: float
    fy2026_q3_cloud_revenue_bn: float
    fy2026_q3_cloud_gross_margin_pct: float
    fy2026_q3_ai_arr_bn: float
    calendar_2026_capex_guidance_bn: float


class MarketSpec(BaseModel):
    current_share_price: float
    current_market_cap_bn: float
    current_reported_eps_ttm: float
    current_normalized_eps_ttm: float
    current_pe_ttm: float
    estimated_diluted_shares_bn: float


class Scenario(BaseModel):
    meta: dict[str, Any]
    business_model_type: str = "cloud_software_ai_infrastructure"
    market: MarketSpec
    base_financials: BaseFinancials | None = None
    simulation: SimulationSpec
    revenue_lines: list[RevenueLine] = Field(default_factory=list)
    opex: OpexSpec | None = None
    capex: CapexSpec | None = None
    shock: ShockSpec | None = None
    capital_return: CapitalReturnSpec
    valuation: ValuationSpec
    business_model_inputs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def sanity_check(self) -> "Scenario":
        if self.business_model_type != "cloud_software_ai_infrastructure":
            if self.market.current_share_price <= 0:
                raise ValueError("current_share_price must be positive")
            return self

        if self.base_financials is None:
            raise ValueError("cloud/software/AI model requires base_financials")
        total_revenue = sum(line.starting_revenue_bn for line in self.revenue_lines)
        base_revenue = self.base_financials.fy2025_revenue_bn
        if total_revenue <= 0:
            raise ValueError("revenue line total must be positive")
        if abs(total_revenue - base_revenue) / base_revenue > 0.25:
            raise ValueError("revenue lines do not roughly reconcile to FY2025 revenue")
        if self.market.current_share_price <= 0:
            raise ValueError("current_share_price must be positive")
        return self


class HistogramTrimPercentiles(BaseModel):
    lower: float = 0.01
    upper: float = 0.99


class HistogramOutputConfig(BaseModel):
    bucket_count: int = Field(default=20, ge=5, le=100)
    bucket_mode: Literal["auto_full_range", "auto_percentile_trimmed", "fixed_range"] = (
        "auto_percentile_trimmed"
    )
    trim_percentiles: HistogramTrimPercentiles = HistogramTrimPercentiles()
    include_overflow_buckets: bool = True
    x_metric: str = "total_return_cagr"
    x_axis_format: str = "percent"
    bar_metric: str = "probability"
    overlay_metric: str = "cumulative_probability"
    fixed_min: float | None = None
    fixed_max: float | None = None


class OutputConfig(BaseModel):
    histogram: HistogramOutputConfig = HistogramOutputConfig()


class SimulationRequest(BaseModel):
    scenario: dict[str, Any]
    simulation_count: int | None = Field(default=None, ge=100, le=200000)
    random_seed: int | None = None
    regime_filter: RegimeFilter = "all"
    output: OutputConfig = OutputConfig()


class SensitivityRequest(BaseModel):
    scenario: dict[str, Any]
    simulation_count: int = Field(default=5000, ge=100, le=50000)
    random_seed: int | None = None
    variables: list[str]
