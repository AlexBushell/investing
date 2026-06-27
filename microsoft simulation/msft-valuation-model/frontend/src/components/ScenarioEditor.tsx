import type { ChangeEvent } from "react";

import type { OutputConfig, Scenario } from "../types";

type Props = {
  scenario: Scenario;
  outputConfig: OutputConfig;
  onNumberChange: (path: string, value: number) => void;
  onOutputNumberChange: (path: string, value: number) => void;
  onOutputModeChange: (value: OutputConfig["histogram"]["bucket_mode"]) => void;
  onToggleOverflow: (checked: boolean) => void;
  onLoadScenario: (event: ChangeEvent<HTMLInputElement>) => void;
  onSaveScenario: () => void;
  onReset: () => void;
};

function NumberField({
  label,
  value,
  onChange,
  step = "0.01",
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : ""}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function DistributionFieldSet({
  title,
  basePath,
  distribution,
  onNumberChange,
}: {
  title: string;
  basePath: string;
  distribution: { min: number; mode: number; max: number };
  onNumberChange: (path: string, value: number) => void;
}) {
  return (
    <section className="distribution-block">
      <div className="distribution-header">
        <h4>{title}</h4>
        <span className="distribution-chip">PERT</span>
      </div>
      <div className="distribution-grid">
        <NumberField
          label="Min"
          value={distribution.min}
          onChange={(value) => onNumberChange(`${basePath}.min`, value)}
        />
        <NumberField
          label="Mode"
          value={distribution.mode}
          onChange={(value) => onNumberChange(`${basePath}.mode`, value)}
        />
        <NumberField
          label="Max"
          value={distribution.max}
          onChange={(value) => onNumberChange(`${basePath}.max`, value)}
        />
      </div>
    </section>
  );
}

export function ScenarioEditor({
  scenario,
  outputConfig,
  onNumberChange,
  onOutputNumberChange,
  onOutputModeChange,
  onToggleOverflow,
  onLoadScenario,
  onSaveScenario,
  onReset,
}: Props) {
  return (
    <div className="editor-stack">
      <section className="panel">
        <div className="panel-heading compact">
          <h2>Run Controls</h2>
        </div>
        <div className="field-grid">
          <NumberField
            label="Current share price"
            value={scenario.market.current_share_price}
            onChange={(value) => onNumberChange("market.current_share_price", value)}
          />
          <NumberField
            label="Reported TTM EPS"
            value={scenario.market.current_reported_eps_ttm}
            onChange={(value) => onNumberChange("market.current_reported_eps_ttm", value)}
          />
          <NumberField
            label="Normalised TTM EPS"
            value={scenario.market.current_normalized_eps_ttm}
            onChange={(value) => onNumberChange("market.current_normalized_eps_ttm", value)}
          />
          <NumberField
            label="Quoted TTM PE"
            value={scenario.market.current_pe_ttm}
            onChange={(value) => onNumberChange("market.current_pe_ttm", value)}
          />
          <NumberField
            label="Target CAGR"
            value={scenario.simulation.target_cagr}
            onChange={(value) => onNumberChange("simulation.target_cagr", value)}
          />
          <NumberField
            label="Simulation count"
            value={scenario.simulation.simulation_count}
            step="100"
            onChange={(value) => onNumberChange("simulation.simulation_count", value)}
          />
          <NumberField
            label="Scenario seed"
            value={scenario.simulation.random_seed}
            step="1"
            onChange={(value) => onNumberChange("simulation.random_seed", value)}
          />
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading compact">
          <h2>Valuation & Capital Return</h2>
        </div>
        <div className="field-grid">
          <NumberField
            label="EPS valuation weight"
            value={scenario.valuation.valuation_weight_eps}
            onChange={(value) => onNumberChange("valuation.valuation_weight_eps", value)}
          />
          <NumberField
            label="FCF valuation weight"
            value={scenario.valuation.valuation_weight_fcf}
            onChange={(value) => onNumberChange("valuation.valuation_weight_fcf", value)}
          />
        </div>
        <div className="line-section-grid">
          <DistributionFieldSet
            title="Buyback % Post-dividend FCF"
            basePath="capital_return.buyback_pct_of_post_dividend_fcf"
            distribution={scenario.capital_return.buyback_pct_of_post_dividend_fcf}
            onNumberChange={onNumberChange}
          />
          <DistributionFieldSet
            title="Max Annual Share Reduction"
            basePath="capital_return.max_annual_share_reduction"
            distribution={scenario.capital_return.max_annual_share_reduction}
            onNumberChange={onNumberChange}
          />
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading compact">
          <h2>Distribution Controls</h2>
        </div>
        <div className="field-grid">
          <NumberField
            label="Bucket count"
            value={outputConfig.histogram.bucket_count}
            step="1"
            onChange={(value) => onOutputNumberChange("histogram.bucket_count", value)}
          />
          <label className="field">
            <span>Bucket mode</span>
            <select
              value={outputConfig.histogram.bucket_mode}
              onChange={(event) =>
                onOutputModeChange(event.target.value as OutputConfig["histogram"]["bucket_mode"])
              }
            >
              <option value="auto_percentile_trimmed">Auto percentile trimmed</option>
              <option value="auto_full_range">Auto full range</option>
              <option value="fixed_range">Fixed range</option>
            </select>
          </label>
          <NumberField
            label="Lower trim"
            value={outputConfig.histogram.trim_percentiles.lower}
            step="0.01"
            onChange={(value) => onOutputNumberChange("histogram.trim_percentiles.lower", value)}
          />
          <NumberField
            label="Upper trim"
            value={outputConfig.histogram.trim_percentiles.upper}
            step="0.01"
            onChange={(value) => onOutputNumberChange("histogram.trim_percentiles.upper", value)}
          />
          <NumberField
            label="Fixed min"
            value={outputConfig.histogram.fixed_min ?? -0.1}
            step="0.01"
            onChange={(value) => onOutputNumberChange("histogram.fixed_min", value)}
          />
          <NumberField
            label="Fixed max"
            value={outputConfig.histogram.fixed_max ?? 0.2}
            step="0.01"
            onChange={(value) => onOutputNumberChange("histogram.fixed_max", value)}
          />
          <label className="toggle-field">
            <input
              type="checkbox"
              checked={outputConfig.histogram.include_overflow_buckets}
              onChange={(event) => onToggleOverflow(event.target.checked)}
            />
            <span>Include overflow buckets</span>
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading compact">
          <h2>Revenue Lines</h2>
        </div>
        <div className="line-stack">
          {scenario.revenue_lines.map((line: any, index: number) => (
            <details className="line-card" key={line.name} open={index === 0}>
              <summary className="line-summary">
                <div className="line-summary-copy">
                  <h3>{line.name}</h3>
                  <span>
                    ${line.starting_revenue_bn}bn starting revenue · {(line.gross_margin.start * 100).toFixed(0)}%
                    starting gross margin
                  </span>
                </div>
              </summary>

              <div className="line-card-body">
                <p className="line-description">{line.description}</p>
                <div className="line-card-metrics">
                  <NumberField
                    label="Starting revenue"
                    value={line.starting_revenue_bn}
                    onChange={(value) =>
                      onNumberChange(`revenue_lines.${index}.starting_revenue_bn`, value)
                    }
                  />
                  <NumberField
                    label="Starting gross margin"
                    value={line.gross_margin.start}
                    onChange={(value) =>
                      onNumberChange(`revenue_lines.${index}.gross_margin.start`, value)
                    }
                  />
                </div>

                <div className="line-section-grid">
                  <DistributionFieldSet
                    title="Growth Years 1-3"
                    basePath={`revenue_lines.${index}.growth.years_1_to_3`}
                    distribution={line.growth.years_1_to_3}
                    onNumberChange={onNumberChange}
                  />
                  <DistributionFieldSet
                    title="Growth Years 4-7"
                    basePath={`revenue_lines.${index}.growth.years_4_to_7`}
                    distribution={line.growth.years_4_to_7}
                    onNumberChange={onNumberChange}
                  />
                  <DistributionFieldSet
                    title="Growth Years 8-10"
                    basePath={`revenue_lines.${index}.growth.years_8_to_10`}
                    distribution={line.growth.years_8_to_10}
                    onNumberChange={onNumberChange}
                  />
                  <DistributionFieldSet
                    title="Terminal Gross Margin"
                    basePath={`revenue_lines.${index}.gross_margin.terminal`}
                    distribution={line.gross_margin.terminal}
                    onNumberChange={onNumberChange}
                  />
                  <DistributionFieldSet
                    title="Maintenance Capex % Revenue"
                    basePath={`revenue_lines.${index}.capex_intensity.maintenance_pct_of_revenue`}
                    distribution={line.capex_intensity.maintenance_pct_of_revenue}
                    onNumberChange={onNumberChange}
                  />
                  <DistributionFieldSet
                    title="Growth Capex % Incremental Revenue"
                    basePath={`revenue_lines.${index}.capex_intensity.growth_pct_of_incremental_revenue`}
                    distribution={line.capex_intensity.growth_pct_of_incremental_revenue}
                    onNumberChange={onNumberChange}
                  />
                </div>
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading compact">
          <h2>Scenario Files</h2>
        </div>
        <div className="action-row">
          <button type="button" onClick={onSaveScenario}>
            Save scenario JSON
          </button>
          <label className="button-like">
            Load scenario JSON
            <input type="file" accept="application/json" onChange={onLoadScenario} hidden />
          </label>
          <button type="button" className="ghost-button" onClick={onReset}>
            Reset to API default
          </button>
        </div>
      </section>
    </div>
  );
}
