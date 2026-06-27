import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ConfidencePriceCurve as ConfidencePriceCurveData } from "../types";

type Props = {
  curve: ConfidencePriceCurveData;
};

function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function ConfidencePriceCurve({ curve }: Props) {
  const data = curve.points.map((point) => ({
    ...point,
    confidenceCagrPct: point.confidence_cagr * 100,
  }));

  return (
    <section className="panel chart-panel">
      <div className="panel-heading">
        <div>
          <h2>85% confidence return by entry price</h2>
          <p>Line shows the CAGR that 85% of simulated paths still beat at each purchase price.</p>
        </div>
        <div className="chart-pills">
          <div className="confidence-pill">
            {formatMoney(curve.target_return_price)} for {formatPercent(curve.target_cagr)}
          </div>
        </div>
      </div>
      <div className="chart-frame medium">
        <ResponsiveContainer width="100%" height={330}>
          <LineChart data={data} margin={{ top: 16, right: 28, bottom: 30, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(28, 39, 52, 0.12)" />
            <XAxis
              dataKey="entry_price"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value) => formatMoney(Number(value))}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              formatter={(value: number) => [`${value.toFixed(2)}%`, "85% confidence CAGR"]}
              labelFormatter={(value) => `Entry price: ${formatMoney(Number(value))}`}
              contentStyle={{
                borderRadius: 16,
                border: "1px solid rgba(28, 39, 52, 0.12)",
                background: "#fffdf8",
              }}
            />
            <ReferenceLine
              x={curve.current_share_price}
              stroke="#355c7d"
              strokeDasharray="4 4"
              label={{ value: "Today", position: "insideTop", fill: "#355c7d", fontSize: 12 }}
            />
            <ReferenceLine
              x={curve.target_return_price}
              stroke="#0f9d8a"
              strokeDasharray="4 4"
              label={{ value: "85% target price", position: "insideTop", fill: "#0d7b6d", fontSize: 12 }}
            />
            <ReferenceLine
              y={curve.target_cagr * 100}
              stroke="#c96f31"
              strokeDasharray="3 3"
              label={{ value: "Target CAGR", position: "insideRight", fill: "#8f5a2a", fontSize: 12 }}
            />
            <Line
              type="monotone"
              dataKey="confidenceCagrPct"
              name="85% confidence CAGR"
              stroke="#0f9d8a"
              strokeWidth={3}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
