import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ProbabilityDistribution } from "../types";

type Props = {
  distribution: ProbabilityDistribution;
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function ProbabilityHistogramWithConfidenceOverlay({ distribution }: Props) {
  const confidenceFloor = distribution.confidence_floor;
  const confidenceFloorBucket = distribution.buckets.find((bucket) => {
    if (bucket.lower_bound === null) {
      return confidenceFloor.value < (bucket.upper_bound ?? Number.POSITIVE_INFINITY);
    }
    if (bucket.upper_bound === null) {
      return confidenceFloor.value >= bucket.lower_bound;
    }
    return bucket.lower_bound <= confidenceFloor.value && confidenceFloor.value < bucket.upper_bound;
  });

  const data = distribution.buckets.map((bucket) => ({
    ...bucket,
    probabilityPct: bucket.probability * 100,
    cumulativePct: bucket.cumulative_probability * 100,
    exceedPct: bucket.probability_exceeding_upper_bound * 100,
    fill: bucket.contains_target ? "#c96f31" : "#355c7d",
  }));

  return (
    <section className="panel chart-panel">
      <div className="panel-heading">
        <div>
          <h2>10-year CAGR probability distribution</h2>
          <p>Bars show probability by return bucket. Line shows cumulative confidence level.</p>
        </div>
        <div className="chart-pills">
          <div className="confidence-pill">
            {formatPercent(confidenceFloor.value)} 85% floor
          </div>
          <div className="target-pill">{formatPercent(distribution.target_cagr)} target</div>
        </div>
      </div>
      <div className="chart-frame">
        <ResponsiveContainer width="100%" height={420}>
          <ComposedChart data={data} margin={{ top: 16, right: 20, bottom: 40, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(28, 39, 52, 0.12)" />
            <XAxis
              dataKey="label"
              angle={-20}
              textAnchor="end"
              tick={{ fontSize: 11 }}
              height={70}
              interval={0}
            />
            <YAxis
              yAxisId="left"
              tickFormatter={(value) => `${value.toFixed(0)}%`}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, 100]}
              tickFormatter={(value) => `${value.toFixed(0)}%`}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              formatter={(value: number, name: string) => {
                if (name === "Probability") return [`${value.toFixed(2)}%`, name];
                if (name === "Cumulative confidence") return [`${value.toFixed(2)}%`, name];
                if (name === "Probability > upper bound") return [`${value.toFixed(2)}%`, name];
                return [value, name];
              }}
              contentStyle={{
                borderRadius: 16,
                border: "1px solid rgba(28, 39, 52, 0.12)",
                background: "#fffdf8",
              }}
              labelFormatter={(label) => `CAGR range: ${label}`}
            />
            <Legend />
            <ReferenceLine
              yAxisId="right"
              x={data.find((bucket) => bucket.contains_target)?.label}
              stroke="#c96f31"
              strokeDasharray="4 4"
            />
            <ReferenceLine
              yAxisId="right"
              x={confidenceFloorBucket?.label}
              stroke="#0f9d8a"
              strokeDasharray="2 2"
              label={{
                value: "85% floor",
                position: "insideTop",
                fill: "#0d7b6d",
                fontSize: 12,
              }}
            />
            <Bar yAxisId="left" dataKey="probabilityPct" name="Probability" fill="#355c7d" />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="cumulativePct"
              name="Cumulative confidence"
              stroke="#0f9d8a"
              strokeWidth={3}
              dot={false}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="exceedPct"
              name="Probability > upper bound"
              stroke="#d1495b"
              strokeDasharray="6 6"
              strokeWidth={2}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
