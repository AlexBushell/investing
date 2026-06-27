import type { SimulationSummary } from "../types";

type Props = {
  summary: SimulationSummary;
  currentSharePrice: number;
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

function valuationZone(probabilityAboveTarget: number): string {
  if (probabilityAboveTarget >= 0.85) {
    return "Attractive / high confidence";
  }
  if (probabilityAboveTarget >= 0.6) {
    return "Interesting";
  }
  if (probabilityAboveTarget >= 0.35) {
    return "Watchlist / fair";
  }
  if (probabilityAboveTarget >= 0.15) {
    return "Demanding";
  }
  return "Heroic / low odds";
}

const summaryCards = (
  summary: SimulationSummary,
  currentSharePrice: number,
): Array<{ label: string; value: string; tone?: string }> => [
  { label: "Current Share Price", value: formatMoney(currentSharePrice) },
  { label: "Median 10Y CAGR", value: formatPercent(summary.median_cagr), tone: "accent" },
  { label: "P(Beat Target)", value: formatPercent(summary.probability_above_target), tone: "accent" },
  {
    label: "85% Target Return Price",
    value: formatMoney(summary.target_return_85_confidence_price),
    tone: "confidence",
  },
  { label: "P(Negative Return)", value: formatPercent(summary.probability_of_loss) },
  { label: "P50 Terminal Price", value: formatMoney(summary.p50_terminal_share_price) },
  { label: "Valuation Zone", value: valuationZone(summary.probability_above_target) },
];

export function OverviewDashboard({ summary, currentSharePrice }: Props) {
  return (
    <section className="dashboard-grid">
      {summaryCards(summary, currentSharePrice).map((card) => (
        <article className={`metric-card ${card.tone ?? ""}`.trim()} key={card.label}>
          <span className="metric-label">{card.label}</span>
          <strong className="metric-value">{card.value}</strong>
        </article>
      ))}
    </section>
  );
}
