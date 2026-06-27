import type {
  OutputConfig,
  RegimeFilter,
  Scenario,
  ScenarioCatalogItem,
  SensitivityResponse,
  SimulationResponse,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function fetchDefaultScenario(): Promise<Scenario> {
  return request<Scenario>("/scenario/default");
}

export function fetchScenarios(): Promise<ScenarioCatalogItem[]> {
  return request<ScenarioCatalogItem[]>("/scenarios");
}

export function fetchScenarioById(scenarioId: string): Promise<Scenario> {
  return request<Scenario>(`/scenarios/${scenarioId}`);
}

export function simulateScenario(
  scenario: Scenario,
  output: OutputConfig,
  randomSeed: number | null = scenario.simulation?.random_seed ?? null,
  regimeFilter: RegimeFilter = "all",
): Promise<SimulationResponse> {
  return request<SimulationResponse>("/simulate", {
    method: "POST",
    body: JSON.stringify({
      scenario,
      simulation_count: scenario.simulation?.simulation_count,
      random_seed: randomSeed,
      regime_filter: regimeFilter,
      output,
    }),
  });
}

export function runSensitivity(
  scenario: Scenario,
  variables: string[],
  randomSeed: number | null = scenario.simulation?.random_seed ?? null,
): Promise<SensitivityResponse> {
  return request<SensitivityResponse>("/sensitivity", {
    method: "POST",
    body: JSON.stringify({
      scenario,
      simulation_count: 2500,
      random_seed: randomSeed,
      variables,
    }),
  });
}
