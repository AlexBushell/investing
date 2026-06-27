import { useState } from "react";

import type { OutputConfig, Scenario } from "../types";

export const defaultOutputConfig: OutputConfig = {
  histogram: {
    bucket_count: 20,
    bucket_mode: "auto_percentile_trimmed",
    trim_percentiles: {
      lower: 0.01,
      upper: 0.99,
    },
    include_overflow_buckets: true,
    x_metric: "total_return_cagr",
    x_axis_format: "percent",
    bar_metric: "probability",
    overlay_metric: "cumulative_probability",
  },
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function setByPath(target: Record<string, any> | any[], path: string, value: unknown) {
  const keys = path.split(".");
  const next = clone(target);
  let cursor: any = next;
  for (let index = 0; index < keys.length - 1; index += 1) {
    const key = keys[index];
    if (Array.isArray(cursor)) {
      const numericKey = Number(key);
      cursor[numericKey] = clone(cursor[numericKey]);
      cursor = cursor[numericKey];
    } else {
      cursor[key] = clone(cursor[key]);
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

export function useScenarioStore(initialScenario: Scenario | null) {
  const [scenario, setScenario] = useState<Scenario | null>(initialScenario);
  const [outputConfig, setOutputConfig] = useState<OutputConfig>(defaultOutputConfig);

  return {
    scenario,
    setScenario,
    outputConfig,
    setOutputConfig,
    updateScenario(path: string, value: unknown) {
      setScenario((current) => {
        if (!current) {
          return current;
        }
        return setByPath(current, path, value);
      });
    },
  };
}
