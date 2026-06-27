import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { SensitivityItem } from "../types";

type Props = {
  items: SensitivityItem[];
};

export function SensitivityChart({ items }: Props) {
  const data = items.map((item) => ({
    ...item,
    impactPct: item.impact * 100,
  }));

  return (
    <section className="panel chart-panel">
      <div className="panel-heading compact">
        <h2>Tornado Sensitivity</h2>
      </div>
      <div className="chart-frame small">
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={data} layout="vertical" margin={{ top: 10, right: 10, left: 30, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(28, 39, 52, 0.12)" />
            <XAxis type="number" tickFormatter={(value) => `${value.toFixed(1)}%`} />
            <YAxis dataKey="variable" type="category" width={130} tick={{ fontSize: 12 }} />
            <Tooltip formatter={(value: number) => `${value.toFixed(2)}%`} />
            <Bar dataKey="impactPct" fill="#d1495b" radius={[0, 8, 8, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
