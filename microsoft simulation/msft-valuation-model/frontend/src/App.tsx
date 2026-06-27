import { type ChangeEvent, startTransition, useEffect, useMemo, useState } from "react";

import {
  fetchDefaultScenario,
  fetchScenarioById,
  fetchScenarios,
  runSensitivity,
  simulateScenario,
} from "./api/client";
import { ConfidencePriceCurve } from "./components/ConfidencePriceCurve";
import { Layout } from "./components/Layout";
import { OverviewDashboard } from "./components/OverviewDashboard";
import { PercentileTable } from "./components/PercentileTable";
import { ProbabilityHistogramWithConfidenceOverlay } from "./components/ProbabilityHistogramWithConfidenceOverlay";
import { RegimeDiagnostics } from "./components/RegimeDiagnostics";
import { ScenarioEditor } from "./components/ScenarioEditor";
import { SensitivityChart } from "./components/SensitivityChart";
import { defaultOutputConfig, useScenarioStore } from "./state/useScenarioStore";
import type {
  RegimeFilter,
  Scenario,
  ScenarioCatalogItem,
  SensitivityResponse,
  SimulationResponse,
  RegimeMetadata,
} from "./types";
import "./styles.css";

const sensitivityVariables = [
  "terminal_pe",
  "ai_revenue_growth",
  "gpu_economic_life",
  "shock_probability",
  "capex_intensity",
];

const genericSensitivityVariables = [
  "terminal_pe",
  "terminal_fcf_multiple",
  "generic_revenue_growth",
  "generic_operating_margin",
  "generic_reinvestment",
];

const housebuilderSensitivityVariables = [
  "terminal_pe",
  "terminal_price_to_book",
  "terminal_dividend_yield",
  "completions_growth",
  "average_selling_price_growth",
  "gross_margin",
  "land_reinvestment_pct_revenue",
  "housing_downturn_probability",
];

const lowCostGymSensitivityVariables = [
  "terminal_pe",
  "terminal_fcf_multiple",
  "gym_new_sites",
  "gym_revenue_per_site_growth",
  "gym_cash_margin",
  "gym_growth_capex",
  "gym_lease_liability",
  "gym_consumer_squeeze_probability",
];

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

type RunOptions = {
  reroll?: boolean;
  forcedSeed?: number | null;
};

function formatRunCount(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatRegimeFilter(value: RegimeFilter, metadata: RegimeMetadata[] = []): string {
  if (value === "all") {
    return "All regimes";
  }
  return metadata.find((item) => item.key === value)?.label ?? value.charAt(0).toUpperCase() + value.slice(1);
}

function sensitivityVariablesForScenario(nextScenario: Scenario): string[] {
  if (nextScenario.business_model_type === "generic_revenue_margin_fcf") {
    return genericSensitivityVariables;
  }
  if (nextScenario.business_model_type === "housebuilder") {
    return housebuilderSensitivityVariables;
  }
  if (nextScenario.business_model_type === "low_cost_gym_ifrs16") {
    return lowCostGymSensitivityVariables;
  }
  return sensitivityVariables;
}

function scenarioDescription(nextScenario: Scenario | null): string {
  if (nextScenario?.business_model_type === "generic_revenue_margin_fcf") {
    return "Probability of clearing a target CAGR under revenue growth, margin, reinvestment, capital return, and terminal valuation uncertainty.";
  }
  if (nextScenario?.business_model_type === "housebuilder") {
    return "Probability of clearing a target CAGR under completions, average selling price, land reinvestment, book value, dividends, and housing downturn uncertainty.";
  }
  if (nextScenario?.business_model_type === "low_cost_gym_ifrs16") {
    return "Probability of clearing a target CAGR under site rollout, revenue per gym, maintenance capex, growth capex, IFRS16 lease burden, and trade-down tailwinds.";
  }
  return "Probability of clearing a target CAGR under AI growth, capex strain, margin pressure, and terminal valuation uncertainty.";
}

function setByPath(target: Record<string, any>, path: string, value: unknown): Record<string, any> {
  const keys = path.split(".");
  const next = clone(target);
  let cursor: Record<string, any> = next;
  for (let index = 0; index < keys.length - 1; index += 1) {
    const key = keys[index];
    const nextNode = Array.isArray(cursor) ? cursor[Number(key)] : cursor[key];
    if (Array.isArray(cursor)) {
      cursor[Number(key)] = clone(nextNode);
      cursor = cursor[Number(key)];
    } else {
      cursor[key] = clone(nextNode);
      cursor = cursor[key];
    }
  }
  const finalKey = keys[keys.length - 1];
  if (Array.isArray(cursor)) {
    cursor[Number(finalKey)] = value;
  } else {
    cursor[finalKey] = value;
  }
  return next;
}

export default function App() {
  const [initialScenario, setInitialScenario] = useState<Scenario | null>(null);
  const { scenario, setScenario, outputConfig, setOutputConfig, updateScenario } =
    useScenarioStore(initialScenario);
  const [simulation, setSimulation] = useState<SimulationResponse | null>(null);
  const [sensitivity, setSensitivity] = useState<SensitivityResponse | null>(null);
  const [status, setStatus] = useState("Loading default scenario...");
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [lastRunSeed, setLastRunSeed] = useState<number | null>(null);
  const [regimeFilter, setRegimeFilter] = useState<RegimeFilter>("all");
  const [scenarioCatalog, setScenarioCatalog] = useState<ScenarioCatalogItem[]>([]);
  const [activeScenarioId, setActiveScenarioId] = useState("msft_cloud_ai_default");

  useEffect(() => {
    void (async () => {
      try {
        const catalog = await fetchScenarios();
        const defaultScenarioId =
          catalog.find((item) => item.scenario_id === "msft_cloud_ai_default")?.scenario_id ??
          catalog[0]?.scenario_id ??
          "msft_cloud_ai_default";
        const defaultScenario = await fetchScenarioById(defaultScenarioId);
        setScenarioCatalog(catalog);
        setActiveScenarioId(defaultScenarioId);
        setInitialScenario(defaultScenario);
        setScenario(defaultScenario);
        await handleRun(defaultScenario, defaultOutputConfig, { reroll: false }, "all");
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load default scenario.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setScenario]);

  async function handleRun(
    nextScenario = scenario,
    nextOutput = outputConfig,
    options: RunOptions = { reroll: true },
    selectedRegimeFilter = regimeFilter,
  ) {
    if (!nextScenario) {
      return;
    }

    const runSeed =
      options.forcedSeed !== undefined
        ? options.forcedSeed
        : options.reroll
          ? Math.floor(Math.random() * 2_147_483_647)
          : (nextScenario.simulation?.random_seed ?? null);
    const regimeStatus = selectedRegimeFilter === "all" ? "" : ` (${selectedRegimeFilter} regime)`;

    setIsRunning(true);
    setError(null);
    setStatus(
      runSeed === null
        ? `Running unseeded simulation${regimeStatus}...`
        : `Running simulation${regimeStatus} with seed ${runSeed}...`,
    );

    try {
      const [simulationResult, sensitivityResult] = await Promise.all([
        simulateScenario(nextScenario, nextOutput, runSeed, selectedRegimeFilter),
        runSensitivity(nextScenario, sensitivityVariablesForScenario(nextScenario), runSeed),
      ]);

      startTransition(() => {
        setSimulation(simulationResult);
        setSensitivity(sensitivityResult);
      });
      setLastRunSeed(runSeed);
      setStatus(
        runSeed === null
          ? `Simulation complete${regimeStatus}.`
          : `Simulation complete${regimeStatus}. Seed ${runSeed}.`,
      );
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Simulation failed.");
      setStatus("Run failed.");
    } finally {
      setIsRunning(false);
    }
  }

  function handleOutputNumberChange(path: string, value: number) {
    setOutputConfig((current) => setByPath(current, path, value) as typeof current);
  }

  function handleOutputModeChange(value: "auto_full_range" | "auto_percentile_trimmed" | "fixed_range") {
    setOutputConfig((current) => ({
      ...current,
      histogram: {
        ...current.histogram,
        bucket_mode: value,
      },
    }));
  }

  function handleToggleOverflow(checked: boolean) {
    setOutputConfig((current) => ({
      ...current,
      histogram: {
        ...current.histogram,
        include_overflow_buckets: checked,
      },
    }));
  }

  async function resetScenario() {
    try {
      const nextScenario =
        activeScenarioId === "custom"
          ? await fetchDefaultScenario()
          : await fetchScenarioById(activeScenarioId);
      if (activeScenarioId === "custom") {
        setActiveScenarioId("msft_cloud_ai_default");
      }
      setScenario(nextScenario);
      setOutputConfig(defaultOutputConfig);
      setRegimeFilter("all");
      setSimulation(null);
      setSensitivity(null);
      await handleRun(nextScenario, defaultOutputConfig, { reroll: false }, "all");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to reset scenario.");
    }
  }

  function saveScenario() {
    if (!scenario) {
      return;
    }
    const blob = new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${scenario.meta?.ticker ?? "valuation"}-scenario.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function loadScenario(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    void file.text().then(async (text) => {
      const nextScenario = JSON.parse(text) as Scenario;
      setScenario(nextScenario);
      setActiveScenarioId("custom");
      setRegimeFilter("all");
      setSimulation(null);
      setSensitivity(null);
      setStatus(`Loaded ${file.name}. Running scenario...`);
      await handleRun(nextScenario, outputConfig, { reroll: false }, "all");
    }).catch(() => {
      setError("Could not parse uploaded scenario JSON.");
    });
  }

  async function handleScenarioSelection(scenarioId: string) {
    try {
      const nextScenario = await fetchScenarioById(scenarioId);
      setActiveScenarioId(scenarioId);
      setScenario(nextScenario);
      setOutputConfig(defaultOutputConfig);
      setRegimeFilter("all");
      setSimulation(null);
      setSensitivity(null);
      setStatus(`Loaded ${nextScenario.meta?.company ?? scenarioId}. Running scenario...`);
      await handleRun(nextScenario, defaultOutputConfig, { reroll: false }, "all");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load scenario.");
      setStatus("Scenario load failed.");
    }
  }

  async function handleRegimeFilterChange(nextFilter: RegimeFilter) {
    if (!scenario) {
      return;
    }

    const runSeed = lastRunSeed ?? scenario.simulation?.random_seed ?? null;
    const regimeStatus = nextFilter === "all" ? "" : ` (${nextFilter} regime)`;
    const previousFilter = regimeFilter;
    setRegimeFilter(nextFilter);
    setIsRunning(true);
    setError(null);
    setStatus(
      runSeed === null
        ? `Filtering unseeded simulation${regimeStatus}...`
        : `Filtering simulation${regimeStatus} with seed ${runSeed}...`,
    );

    try {
      const simulationResult = await simulateScenario(scenario, outputConfig, runSeed, nextFilter);
      startTransition(() => {
        setSimulation(simulationResult);
      });
      setLastRunSeed(runSeed);
      setStatus(
        runSeed === null
          ? `Simulation complete${regimeStatus}.`
          : `Simulation complete${regimeStatus}. Seed ${runSeed}.`,
      );
    } catch (filterError) {
      setRegimeFilter(previousFilter);
      setError(filterError instanceof Error ? filterError.message : "Regime filter failed.");
      setStatus("Regime filter failed.");
    } finally {
      setIsRunning(false);
    }
  }

  const header = useMemo(
    () => (
      <div className="hero-copy">
        <div>
          <p className="eyebrow">Probabilistic Stock Valuation Cockpit</p>
          <h1>{scenario?.meta?.ticker ?? "Stock"} valuation cockpit</h1>
          <p className="hero-text">{scenarioDescription(scenario)}</p>
        </div>
        <div className="hero-actions">
          <label className="scenario-picker">
            <span>Scenario</span>
            <select
              value={activeScenarioId}
              onChange={(event) => void handleScenarioSelection(event.target.value)}
              disabled={isRunning}
            >
              {activeScenarioId === "custom" ? (
                <option value="custom" disabled>
                  Custom uploaded scenario
                </option>
              ) : null}
              {scenarioCatalog.map((item) => (
                <option key={item.scenario_id} value={item.scenario_id}>
                  {item.ticker} - {item.company}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => void handleRun()} disabled={!scenario || isRunning}>
            {isRunning ? "Running..." : "Run fresh draw"}
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void handleRun(scenario, outputConfig, { reroll: false })}
            disabled={!scenario || isRunning}
          >
            Replay scenario seed
          </button>
          <button type="button" className="ghost-button" onClick={() => void resetScenario()}>
            Reload defaults
          </button>
          <span className="status-pill">{lastRunSeed === null ? status : `${status}`}</span>
        </div>
        {error ? <p className="error-banner">{error}</p> : null}
      </div>
    ),
    [activeScenarioId, error, isRunning, lastRunSeed, outputConfig, regimeFilter, scenario, scenarioCatalog, status],
  );

  if (!scenario || !simulation) {
    return (
      <main className="loading-shell">
        <h1>MSFT Valuation Model</h1>
        <p>{error ?? status}</p>
      </main>
    );
  }

  return (
    <Layout
      header={header}
      sidebar={
        <ScenarioEditor
          scenario={scenario}
          outputConfig={outputConfig}
          onNumberChange={updateScenario}
          onOutputNumberChange={handleOutputNumberChange}
          onOutputModeChange={handleOutputModeChange}
          onToggleOverflow={handleToggleOverflow}
          onLoadScenario={loadScenario}
          onSaveScenario={saveScenario}
          onReset={() => void resetScenario()}
        />
      }
      rightRail={
        <>
          <section className="panel">
            <div className="panel-heading compact">
              <h2>Run Notes</h2>
            </div>
            <p className="note-text">
              Do not rely on EPS alone. Compare EPS CAGR with FCF/share CAGR. If EPS rises while
              FCF conversion deteriorates, owner returns may be overstated.
            </p>
          </section>
          <section className="panel">
            <div className="panel-heading compact">
              <h2>Run Context</h2>
            </div>
            <div className="run-context-grid">
              <span>Seed</span>
              <strong>{lastRunSeed === null ? "Unseeded" : lastRunSeed}</strong>
              <span>Regime lens</span>
              <strong>{formatRegimeFilter(simulation.regime_filter, simulation.regime_metadata)}</strong>
              <span>Simulations shown</span>
              <strong>
                {formatRunCount(simulation.filtered_simulation_count)} /{" "}
                {formatRunCount(simulation.base_simulation_count)}
              </strong>
            </div>
          </section>
          <RegimeDiagnostics
            diagnostics={simulation.diagnostics}
            regimeMetadata={simulation.regime_metadata}
            activeFilter={regimeFilter}
            onFilterChange={(nextFilter) => void handleRegimeFilterChange(nextFilter)}
          />
          {sensitivity ? <SensitivityChart items={sensitivity.items} /> : null}
        </>
      }
    >
      <OverviewDashboard
        summary={simulation.summary}
        currentSharePrice={scenario.market.current_share_price}
      />
      <ConfidencePriceCurve curve={simulation.confidence_price_curve} />
      <ProbabilityHistogramWithConfidenceOverlay distribution={simulation.distribution} />
      <PercentileTable rows={simulation.percentiles} />
    </Layout>
  );
}
