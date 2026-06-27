import { type ChangeEvent, startTransition, useEffect, useMemo, useState } from "react";

import { fetchDefaultScenario, runSensitivity, simulateScenario } from "./api/client";
import { Layout } from "./components/Layout";
import { OverviewDashboard } from "./components/OverviewDashboard";
import { PercentileTable } from "./components/PercentileTable";
import { ProbabilityHistogramWithConfidenceOverlay } from "./components/ProbabilityHistogramWithConfidenceOverlay";
import { RegimeDiagnostics } from "./components/RegimeDiagnostics";
import { ScenarioEditor } from "./components/ScenarioEditor";
import { SensitivityChart } from "./components/SensitivityChart";
import { defaultOutputConfig, useScenarioStore } from "./state/useScenarioStore";
import type { RegimeFilter, Scenario, SensitivityResponse, SimulationResponse } from "./types";
import "./styles.css";

const sensitivityVariables = [
  "terminal_pe",
  "ai_revenue_growth",
  "gpu_economic_life",
  "shock_probability",
  "capex_intensity",
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

function formatRegimeFilter(value: RegimeFilter): string {
  if (value === "all") {
    return "All regimes";
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
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

  useEffect(() => {
    void (async () => {
      try {
        const defaultScenario = await fetchDefaultScenario();
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
        runSensitivity(nextScenario, sensitivityVariables, runSeed),
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
      const defaultScenario = await fetchDefaultScenario();
      setScenario(defaultScenario);
      setOutputConfig(defaultOutputConfig);
      setRegimeFilter("all");
      setSimulation(null);
      setSensitivity(null);
      await handleRun(defaultScenario, defaultOutputConfig, { reroll: false }, "all");
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
    anchor.download = "msft-scenario.json";
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
      setRegimeFilter("all");
      setSimulation(null);
      setSensitivity(null);
      setStatus(`Loaded ${file.name}. Running scenario...`);
      await handleRun(nextScenario, outputConfig, { reroll: false }, "all");
    }).catch(() => {
      setError("Could not parse uploaded scenario JSON.");
    });
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
          <p className="eyebrow">Microsoft Probabilistic Valuation Cockpit</p>
          <h1>MSFT valuation cockpit</h1>
          <p className="hero-text">
            Probability of clearing a target CAGR under AI growth, capex strain, margin pressure,
            and terminal valuation uncertainty.
          </p>
        </div>
        <div className="hero-actions">
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
    [error, isRunning, lastRunSeed, outputConfig, regimeFilter, scenario, status],
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
              <strong>{formatRegimeFilter(simulation.regime_filter)}</strong>
              <span>Simulations shown</span>
              <strong>
                {formatRunCount(simulation.filtered_simulation_count)} /{" "}
                {formatRunCount(simulation.base_simulation_count)}
              </strong>
            </div>
          </section>
          <RegimeDiagnostics
            diagnostics={simulation.diagnostics}
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
      <ProbabilityHistogramWithConfidenceOverlay distribution={simulation.distribution} />
      <PercentileTable rows={simulation.percentiles} />
    </Layout>
  );
}
