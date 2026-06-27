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
  const genericInputs = scenario.business_model_inputs;
  const revenueLines = scenario.revenue_lines ?? [];

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
          {scenario.valuation.terminal_price_to_book ? (
            <NumberField
              label="P/B valuation weight"
              value={scenario.valuation.valuation_weight_price_to_book ?? 0}
              onChange={(value) => onNumberChange("valuation.valuation_weight_price_to_book", value)}
            />
          ) : null}
          {scenario.valuation.terminal_dividend_yield ? (
            <NumberField
              label="Dividend yield valuation weight"
              value={scenario.valuation.valuation_weight_dividend_yield ?? 0}
              onChange={(value) => onNumberChange("valuation.valuation_weight_dividend_yield", value)}
            />
          ) : null}
        </div>
        <div className="line-section-grid">
          <DistributionFieldSet
            title="Terminal PE"
            basePath="valuation.terminal_pe"
            distribution={scenario.valuation.terminal_pe}
            onNumberChange={onNumberChange}
          />
          <DistributionFieldSet
            title="Terminal FCF Multiple"
            basePath="valuation.terminal_fcf_multiple"
            distribution={scenario.valuation.terminal_fcf_multiple}
            onNumberChange={onNumberChange}
          />
          {scenario.valuation.terminal_price_to_book ? (
            <DistributionFieldSet
              title="Terminal Price / Book"
              basePath="valuation.terminal_price_to_book"
              distribution={scenario.valuation.terminal_price_to_book}
              onNumberChange={onNumberChange}
            />
          ) : null}
          {scenario.valuation.terminal_dividend_yield ? (
            <DistributionFieldSet
              title="Terminal Dividend Yield"
              basePath="valuation.terminal_dividend_yield"
              distribution={scenario.valuation.terminal_dividend_yield}
              onNumberChange={onNumberChange}
            />
          ) : null}
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

      {scenario.business_model_type === "generic_revenue_margin_fcf" && genericInputs ? (
        <section className="panel">
          <div className="panel-heading compact">
            <h2>Generic Operating Model</h2>
          </div>
          <div className="line-card-metrics">
            <NumberField
              label="Starting revenue"
              value={genericInputs.starting_revenue_bn}
              onChange={(value) => onNumberChange("business_model_inputs.starting_revenue_bn", value)}
            />
            <NumberField
              label="Starting operating margin"
              value={genericInputs.operating_margin.start}
              onChange={(value) => onNumberChange("business_model_inputs.operating_margin.start", value)}
            />
          </div>
          <div className="line-section-grid">
            <DistributionFieldSet
              title="Revenue Growth Years 1-3"
              basePath="business_model_inputs.revenue_growth.years_1_to_3"
              distribution={genericInputs.revenue_growth.years_1_to_3}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Revenue Growth Years 4-7"
              basePath="business_model_inputs.revenue_growth.years_4_to_7"
              distribution={genericInputs.revenue_growth.years_4_to_7}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Revenue Growth Years 8-10"
              basePath="business_model_inputs.revenue_growth.years_8_to_10"
              distribution={genericInputs.revenue_growth.years_8_to_10}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Terminal Operating Margin"
              basePath="business_model_inputs.operating_margin.terminal"
              distribution={genericInputs.operating_margin.terminal}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Maintenance Investment % Revenue"
              basePath="business_model_inputs.maintenance_investment_pct_revenue"
              distribution={genericInputs.maintenance_investment_pct_revenue}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Growth Investment % Incremental Revenue"
              basePath="business_model_inputs.growth_investment_pct_incremental_revenue"
              distribution={genericInputs.growth_investment_pct_incremental_revenue}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Working Capital % Incremental Revenue"
              basePath="business_model_inputs.working_capital_pct_incremental_revenue"
              distribution={genericInputs.working_capital_pct_incremental_revenue}
              onNumberChange={onNumberChange}
            />
          </div>
        </section>
      ) : null}

      {scenario.business_model_type === "housebuilder" && genericInputs ? (
        <section className="panel">
          <div className="panel-heading compact">
            <h2>Housebuilder Model</h2>
          </div>
          <div className="line-card-metrics">
            <NumberField
              label="Starting completions"
              value={genericInputs.starting_completions}
              step="100"
              onChange={(value) => onNumberChange("business_model_inputs.starting_completions", value)}
            />
            <NumberField
              label="Starting ASP"
              value={genericInputs.starting_average_selling_price}
              step="1000"
              onChange={(value) => onNumberChange("business_model_inputs.starting_average_selling_price", value)}
            />
            <NumberField
              label="Starting book value"
              value={genericInputs.starting_book_value_bn}
              onChange={(value) => onNumberChange("business_model_inputs.starting_book_value_bn", value)}
            />
          </div>
          <div className="line-section-grid">
            <DistributionFieldSet
              title="Completions Growth Years 1-3"
              basePath="business_model_inputs.completions_growth.years_1_to_3"
              distribution={genericInputs.completions_growth.years_1_to_3}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Completions Growth Years 4-7"
              basePath="business_model_inputs.completions_growth.years_4_to_7"
              distribution={genericInputs.completions_growth.years_4_to_7}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Completions Growth Years 8-10"
              basePath="business_model_inputs.completions_growth.years_8_to_10"
              distribution={genericInputs.completions_growth.years_8_to_10}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="ASP Growth Years 1-3"
              basePath="business_model_inputs.asp_growth.years_1_to_3"
              distribution={genericInputs.asp_growth.years_1_to_3}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="ASP Growth Years 4-7"
              basePath="business_model_inputs.asp_growth.years_4_to_7"
              distribution={genericInputs.asp_growth.years_4_to_7}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="ASP Growth Years 8-10"
              basePath="business_model_inputs.asp_growth.years_8_to_10"
              distribution={genericInputs.asp_growth.years_8_to_10}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Terminal Gross Margin"
              basePath="business_model_inputs.gross_margin.terminal"
              distribution={genericInputs.gross_margin.terminal}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Operating Cost % Revenue"
              basePath="business_model_inputs.operating_cost_pct_revenue"
              distribution={genericInputs.operating_cost_pct_revenue}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Land Reinvestment % Revenue"
              basePath="business_model_inputs.land_reinvestment_pct_revenue"
              distribution={genericInputs.land_reinvestment_pct_revenue}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Working Capital % Revenue Change"
              basePath="business_model_inputs.working_capital_pct_revenue_change"
              distribution={genericInputs.working_capital_pct_revenue_change}
              onNumberChange={onNumberChange}
            />
            {genericInputs.housing_downturn_shock && (
              <>
                <DistributionFieldSet
                  title="Downturn Probability"
                  basePath="business_model_inputs.housing_downturn_shock.probability"
                  distribution={genericInputs.housing_downturn_shock.probability}
                  onNumberChange={onNumberChange}
                />
                <DistributionFieldSet
                  title="Downturn ASP Decline"
                  basePath="business_model_inputs.housing_downturn_shock.asp_decline"
                  distribution={genericInputs.housing_downturn_shock.asp_decline}
                  onNumberChange={onNumberChange}
                />
              </>
            )}
          </div>
        </section>
      ) : null}

      {scenario.business_model_type === "low_cost_gym_ifrs16" && genericInputs ? (
        <section className="panel">
          <div className="panel-heading compact">
            <h2>Low-cost Gym / IFRS16</h2>
          </div>
          <div className="line-card-metrics">
            <NumberField
              label="Starting sites"
              value={genericInputs.starting_sites}
              step="1"
              onChange={(value) => onNumberChange("business_model_inputs.starting_sites", value)}
            />
            <NumberField
              label="Starting revenue"
              value={genericInputs.starting_revenue_bn}
              onChange={(value) => onNumberChange("business_model_inputs.starting_revenue_bn", value)}
            />
            <NumberField
              label="Non-property net debt"
              value={genericInputs.starting_non_property_net_debt_bn}
              onChange={(value) => onNumberChange("business_model_inputs.starting_non_property_net_debt_bn", value)}
            />
            <NumberField
              label="IFRS16 lease liability"
              value={genericInputs.starting_lease_liability_bn}
              onChange={(value) => onNumberChange("business_model_inputs.starting_lease_liability_bn", value)}
            />
          </div>
          <div className="line-section-grid">
            <DistributionFieldSet
              title="New Sites / Year 1-3"
              basePath="business_model_inputs.new_sites_per_year.years_1_to_3"
              distribution={genericInputs.new_sites_per_year.years_1_to_3}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="New Sites / Year 4-7"
              basePath="business_model_inputs.new_sites_per_year.years_4_to_7"
              distribution={genericInputs.new_sites_per_year.years_4_to_7}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="New Sites / Year 8-10"
              basePath="business_model_inputs.new_sites_per_year.years_8_to_10"
              distribution={genericInputs.new_sites_per_year.years_8_to_10}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Revenue / Site Growth Y1-3"
              basePath="business_model_inputs.revenue_per_site_growth.years_1_to_3"
              distribution={genericInputs.revenue_per_site_growth.years_1_to_3}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Revenue / Site Growth Y4-7"
              basePath="business_model_inputs.revenue_per_site_growth.years_4_to_7"
              distribution={genericInputs.revenue_per_site_growth.years_4_to_7}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Revenue / Site Growth Y8-10"
              basePath="business_model_inputs.revenue_per_site_growth.years_8_to_10"
              distribution={genericInputs.revenue_per_site_growth.years_8_to_10}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Terminal EBITDA Less Rent Margin"
              basePath="business_model_inputs.cash_ebitda_less_rent_margin.terminal"
              distribution={genericInputs.cash_ebitda_less_rent_margin.terminal}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Maintenance Capex % Revenue"
              basePath="business_model_inputs.maintenance_capex_pct_revenue"
              distribution={genericInputs.maintenance_capex_pct_revenue}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Growth Capex / New Site"
              basePath="business_model_inputs.growth_capex_per_new_site_bn"
              distribution={genericInputs.growth_capex_per_new_site_bn}
              onNumberChange={onNumberChange}
            />
            <DistributionFieldSet
              title="Lease Liability / Site"
              basePath="business_model_inputs.lease_liability_per_site_bn"
              distribution={genericInputs.lease_liability_per_site_bn}
              onNumberChange={onNumberChange}
            />
            {genericInputs.consumer_squeeze_shock && (
              <>
                <DistributionFieldSet
                  title="Consumer Squeeze Probability"
                  basePath="business_model_inputs.consumer_squeeze_shock.probability"
                  distribution={genericInputs.consumer_squeeze_shock.probability}
                  onNumberChange={onNumberChange}
                />
                <DistributionFieldSet
                  title="Squeeze Margin Haircut"
                  basePath="business_model_inputs.consumer_squeeze_shock.margin_haircut"
                  distribution={genericInputs.consumer_squeeze_shock.margin_haircut}
                  onNumberChange={onNumberChange}
                />
              </>
            )}
          </div>
        </section>
      ) : null}

      {revenueLines.length ? (
        <section className="panel">
          <div className="panel-heading compact">
            <h2>Revenue Lines</h2>
          </div>
          <div className="line-stack">
            {revenueLines.map((line: any, index: number) => (
              <details className="line-card" key={line.name} open={index === 0}>
                <summary className="line-summary">
                  <div className="line-summary-copy">
                    <h3>{line.name}</h3>
                    <span>
                      ${line.starting_revenue_bn}bn starting revenue -{" "}
                      {(line.gross_margin.start * 100).toFixed(0)}% starting gross margin
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
      ) : null}

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
