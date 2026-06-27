import type { PercentileRow } from "../types";

type Props = {
  rows: PercentileRow[];
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function PercentileTable({ rows }: Props) {
  return (
    <section className="panel">
      <div className="panel-heading compact">
        <h2>Percentile Table</h2>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Percentile</th>
              <th>Terminal Price</th>
              <th>Total Return Multiple</th>
              <th>10Y CAGR</th>
              <th>Year-10 EPS</th>
              <th>Terminal PE</th>
              <th>Year-10 FCF/share</th>
              <th>Terminal FCF Multiple</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.percentile}>
                <td>P{row.percentile}</td>
                <td>{formatMoney(row.terminal_share_price)}</td>
                <td>{row.total_return_multiple.toFixed(2)}x</td>
                <td>{formatPercent(row.cagr)}</td>
                <td>{row.terminal_eps.toFixed(2)}</td>
                <td>{row.terminal_pe.toFixed(1)}x</td>
                <td>{formatMoney(row.terminal_fcf_per_share)}</td>
                <td>{row.terminal_fcf_multiple.toFixed(1)}x</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
