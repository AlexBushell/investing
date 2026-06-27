import type { RegimeFilter, RegimeMetadata, SimulationDiagnostics } from "../types";

type Props = {
  diagnostics: SimulationDiagnostics;
  regimeMetadata: RegimeMetadata[];
  activeFilter: RegimeFilter;
  onFilterChange: (filter: RegimeFilter) => void;
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function RegimeDiagnostics({ diagnostics, regimeMetadata, activeFilter, onFilterChange }: Props) {
  const items = regimeMetadata.length ? regimeMetadata : diagnostics.regime_frequencies;

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
            disabled={item.frequency <= 0}
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
            disabled={item.frequency <= 0}
            key={item.key}
            onClick={() => onFilterChange(item.key)}
          >
            <div className="regime-row">
              <strong>{item.label}</strong>
              <span className="regime-value">{formatPercent(item.frequency)}</span>
            </div>
            <p>{item.description}</p>
          </button>
        ))}
      </div>
      <div className="regime-meta">
        <span>Shock realised: {formatPercent(diagnostics.shock_frequency_realised)}</span>
        <span>Secondary stress: {formatPercent(diagnostics.accelerated_depreciation_frequency_realised)}</span>
      </div>
    </section>
  );
}
