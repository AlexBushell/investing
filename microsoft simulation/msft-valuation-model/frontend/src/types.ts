export type DistributionBucket = {
  bucket_index: number;
  label: string;
  lower_bound: number | null;
  upper_bound: number | null;
  midpoint: number | null;
  count: number;
  probability: number;
  cumulative_probability: number;
  probability_exceeding_upper_bound: number;
  contains_target: boolean;
};

export type ProbabilityDistribution = {
  metric: string;
  bucket_count: number;
  bucket_mode: string;
  target_cagr: number;
  probability_above_target: number;
  probability_below_target: number;
  confidence_floor: {
    confidence_level: number;
    value: number;
    probability_at_or_above: number;
    label: string;
  };
  buckets: DistributionBucket[];
};

export type SimulationSummary = {
  simulation_count: number;
  target_cagr: number;
  probability_above_target: number;
  probability_below_target: number;
  probability_of_loss: number;
  mean_cagr: number;
  median_cagr: number;
  p10_cagr: number;
  p25_cagr: number;
  p50_cagr: number;
  p75_cagr: number;
  p90_cagr: number;
  p95_cagr: number;
  p10_terminal_share_price: number;
  p25_terminal_share_price: number;
  p50_terminal_share_price: number;
  p75_terminal_share_price: number;
  p90_terminal_share_price: number;
  p95_terminal_share_price: number;
  median_year_10_revenue: number;
  median_year_10_eps: number;
  median_year_10_fcf_per_share: number;
  median_terminal_pe: number;
  median_terminal_fcf_multiple: number;
  median_total_capex_to_revenue: number;
  median_maintenance_capex_to_revenue: number;
  median_growth_capex_to_revenue: number;
};

export type PercentileRow = {
  percentile: number;
  terminal_share_price: number;
  total_return_multiple: number;
  cagr: number;
  terminal_eps: number;
  terminal_pe: number;
  terminal_fcf_per_share: number;
  terminal_fcf_multiple: number;
};

export type SensitivityItem = {
  variable: string;
  low_case_median_cagr: number;
  base_case_median_cagr: number;
  high_case_median_cagr: number;
  impact: number;
};

export type SimulationDiagnostics = {
  median_year_10_revenue_bn: number;
  median_year_10_eps: number;
  median_year_10_fcf_per_share: number;
  median_capex_to_revenue: number;
  median_maintenance_capex_to_revenue: number;
  median_growth_capex_to_revenue: number;
  shock_frequency_realised: number;
  accelerated_depreciation_frequency_realised: number;
  regime_frequency_scarcity: number;
  regime_frequency_balanced: number;
  regime_frequency_overbuild: number;
  regime_frequency_disappointment: number;
};

export type RegimeFilter = "all" | "scarcity" | "balanced" | "overbuild" | "disappointment";

export type SimulationResponse = {
  summary: SimulationSummary;
  percentiles: PercentileRow[];
  distribution: ProbabilityDistribution;
  target_marker: {
    value: number;
    label: string;
    probability_above: number;
    probability_below: number;
  };
  fan_chart: Array<Record<string, number | string>>;
  diagnostics: SimulationDiagnostics;
  regime_filter: RegimeFilter;
  base_simulation_count: number;
  filtered_simulation_count: number;
};

export type SensitivityResponse = {
  items: SensitivityItem[];
};

export type HistogramConfig = {
  bucket_count: number;
  bucket_mode: "auto_full_range" | "auto_percentile_trimmed" | "fixed_range";
  trim_percentiles: {
    lower: number;
    upper: number;
  };
  include_overflow_buckets: boolean;
  x_metric: string;
  x_axis_format: string;
  bar_metric: string;
  overlay_metric: string;
  fixed_min?: number;
  fixed_max?: number;
};

export type OutputConfig = {
  histogram: HistogramConfig;
};

export type Scenario = Record<string, any>;
