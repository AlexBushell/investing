from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf


BASE_DIR = Path(__file__).resolve().parent
INPUT_CSV = BASE_DIR / "infrastructure_investments.csv"
OUTPUT_CSV = BASE_DIR / "latest_prices.csv"

# Yahoo Finance uses ".L" for London-listed securities.
YAHOO_TICKERS = {
    "BSIF": "BSIF.L",
    "FGEN": "FGEN.L",
    "GCP": "GCP.L",
    "HICL": "HICL.L",
    "NESF": "NESF.L",
    "TRIG": "TRIG.L",
    "UKW": "UKW.L",
}

LSE_PENCE_TO_GBP = 100.0


@dataclass
class PriceRow:
    symbol: str
    yahoo_ticker: str
    price_gbp: str
    price_date: str
    fetched_at_utc: str
    error: str


def read_symbols(input_csv: Path) -> list[str]:
    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        symbols = {
            row["Symbol"].strip()
            for row in reader
            if row.get("Symbol") and row["Symbol"].strip().lower() != "n/a"
        }
    return sorted(symbols)


def fetch_price(symbol: str, fetched_at_utc: str) -> PriceRow:
    yahoo_ticker = YAHOO_TICKERS.get(symbol, f"{symbol}.L")
    try:
        history = yf.Ticker(yahoo_ticker).history(period="5d", interval="1d", auto_adjust=False)
        if history.empty:
            raise ValueError("No price history returned")

        latest = history.iloc[-1]
        latest_index = history.index[-1]
        price_date = getattr(latest_index, "date", lambda: latest_index)().isoformat()
        close_price_gbp = float(latest["Close"]) / LSE_PENCE_TO_GBP

        return PriceRow(
            symbol=symbol,
            yahoo_ticker=yahoo_ticker,
            price_gbp=f"{close_price_gbp:.6f}",
            price_date=price_date,
            fetched_at_utc=fetched_at_utc,
            error="",
        )
    except Exception as exc:  # pragma: no cover - network/library failures are reported in output
        return PriceRow(
            symbol=symbol,
            yahoo_ticker=yahoo_ticker,
            price_gbp="",
            price_date="",
            fetched_at_utc=fetched_at_utc,
            error=str(exc),
        )


def write_prices(output_csv: Path, rows: list[PriceRow]) -> None:
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "symbol",
                "yahoo_ticker",
                "price_gbp",
                "price_date",
                "fetched_at_utc",
                "error",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def main() -> None:
    symbols = read_symbols(INPUT_CSV)
    fetched_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = [fetch_price(symbol, fetched_at_utc) for symbol in symbols]
    write_prices(OUTPUT_CSV, rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
