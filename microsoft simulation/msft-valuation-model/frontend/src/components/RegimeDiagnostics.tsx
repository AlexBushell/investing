import type { RegimeFilter, SimulationDiagnostics } from "../types";

type Props = {
  diagnostics: SimulationDiagnostics;
  activeFilter: RegimeFilter;
  onFilterChange: (filter: RegimeFilter) => void;
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

const regimeItems = (diagnostics: SimulationDiagnostics) => [
  {
    key: "scarcity" as const,
    label: "AI scarcity / high ROI",
    value: diagnostics.regime_frequency_scarcity,
    description: "Strong AI demand, better margins, and supportive terminal valuation.",
  },
  {
    key: "balanced" as const,
    label: "Balanced growth",
    value: diagnostics.regime_frequency_balanced,
    description: "More normal demand, capex, and valuation outcomes.",
  },
  {
    key: "overbuild" as const,
    label: "Overbuild / price compression",
    value: diagnostics.regime_frequency_overbuild,
    description: "High buildout, weaker utilization, and valuation pressure.",
  },
  {
    key: "disappointment" as const,
    label: "AI disappointment",
    value: diagnostics.regime_frequency_disappointment,
    description: "Slower AI monetization with weaker growth and margin support.",
  },
];

export function RegimeDiagnostics({ diagnostics, activeFilter, onFilterChange }: Props) {
  const items = regimeItems(diagnostics);

  return (
    <section className="panel">
      <div className="panel-heading compact">
        <h2>Regime Mix</h2>
      </div>
      <p className="note-text">
        These frequencies show what share of simulations landed in each latent world state before
        the final return distribution was assembled.
      </p>
      <div className="regime-filter-row" aria-label="Regime filter">
        <button
          type="button"
          className={activeFilter === "all" ? "regime-filter active" : "regime-filter"}
          onClick={() => onFilterChange("all")}
        >
          All regimes
        </button>
        {items.map((item) => (
          <button
            type="button"
            className={activeFilter === item.key ? "regime-filter active" : "regime-filter"}
            disabled={item.value <= 0}
            key={item.key}
            onClick={() => onFilterChange(item.key)}
          >
            {item.label.split(" / ")[0]}
          </button>
        ))}
      </div>
      <div className="regime-stack">
        {items.map((item) => (
          <button
            type="button"
            className={activeFilter === item.key ? "regime-card active" : "regime-card"}
            disabled={item.value <= 0}
            key={item.key}
            onClick={() => onFilterChange(item.key)}
          >
            <div className="regime-row">
              <strong>{item.label}</strong>
              <span className="regime-value">{formatPercent(item.value)}</span>
            </div>
            <p>{item.description}</p>
          </button>
        ))}
      </div>
      <div className="regime-meta">
        <span>Shock realised: {formatPercent(diagnostics.shock_frequency_realised)}</span>
        <span>Accelerated depreciation: {formatPercent(diagnostics.accelerated_depreciation_frequency_realised)}</span>
      </div>
    </section>
  );
}
