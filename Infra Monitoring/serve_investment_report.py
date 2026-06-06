from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yfinance as yf


BASE_DIR = Path(__file__).resolve().parent
INPUT_CSV = BASE_DIR / "infrastructure_investments.csv"
LOGGER = logging.getLogger("infrastructure_report")

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
class PriceInfo:
    price: float
    price_date: str
    fetched_at_utc: str
    error: str


def parse_money(value: str) -> float:
    stripped = (value or "").strip()
    if not stripped or stripped.lower() == "n/a":
        return 0.0
    return float(stripped.replace("\u00a3", "").replace(",", ""))


def parse_number(value: str) -> float:
    stripped = (value or "").strip()
    if not stripped or stripped.lower() == "n/a":
        return 0.0
    return float(stripped.replace(",", ""))


def read_transactions() -> list[dict[str, str]]:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def get_symbols(rows: list[dict[str, str]]) -> list[str]:
    return sorted({
        row["Symbol"].strip()
        for row in rows
        if row.get("Symbol") and row["Symbol"].strip().lower() != "n/a"
    })


def fetch_latest_prices(symbols: list[str]) -> dict[str, PriceInfo]:
    fetched_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    prices: dict[str, PriceInfo] = {}

    for symbol in symbols:
        yahoo_ticker = YAHOO_TICKERS.get(symbol, f"{symbol}.L")
        try:
            history = yf.Ticker(yahoo_ticker).history(period="5d", interval="1d", auto_adjust=False)
            if history.empty:
                raise ValueError("No price history returned")

            latest = history.iloc[-1]
            latest_index = history.index[-1]
            price_date = getattr(latest_index, "date", lambda: latest_index)().isoformat()
            close_price_gbp = float(latest["Close"]) / LSE_PENCE_TO_GBP
            prices[symbol] = PriceInfo(
                price=close_price_gbp,
                price_date=price_date,
                fetched_at_utc=fetched_at_utc,
                error="",
            )
        except Exception as exc:  # pragma: no cover
            prices[symbol] = PriceInfo(
                price=0.0,
                price_date="",
                fetched_at_utc=fetched_at_utc,
                error=str(exc),
            )

    return prices


def build_report(rows: list[dict[str, str]], prices: dict[str, PriceInfo]) -> dict[str, object]:
    positions: dict[str, dict[str, float | str]] = {}
    unclassified_rows: list[dict[str, object]] = []

    for row in rows:
        symbol = (row.get("Symbol") or "").strip()
        if not symbol or symbol.lower() == "n/a":
            continue

        position = positions.setdefault(symbol, {
            "symbol": symbol,
            "sharesBought": 0.0,
            "sharesSold": 0.0,
            "purchaseCost": 0.0,
            "saleProceeds": 0.0,
            "dividends": 0.0,
            "transactions": [],
        })

        quantity = parse_number(row.get("Quantity", ""))
        debit = parse_money(row.get("Debit", ""))
        credit = parse_money(row.get("Credit", ""))
        description = (row.get("Description") or "").strip().lower()
        transaction_type = "other"

        if description.startswith("div"):
            position["dividends"] += credit
            transaction_type = "dividend"
            position["transactions"].append({
                "date": row.get("Date", ""),
                "settlementDate": row.get("Settlement Date", ""),
                "type": transaction_type,
                "quantity": quantity,
                "price": parse_money(row.get("Price", "")) if row.get("Price") else 0.0,
                "debit": debit,
                "credit": credit,
                "description": row.get("Description", ""),
                "reference": row.get("Reference", ""),
            })
            continue

        if quantity > 0 and debit > 0:
            position["sharesBought"] += quantity
            position["purchaseCost"] += debit
            transaction_type = "buy"
            position["transactions"].append({
                "date": row.get("Date", ""),
                "settlementDate": row.get("Settlement Date", ""),
                "type": transaction_type,
                "quantity": quantity,
                "price": parse_money(row.get("Price", "")) if row.get("Price") else 0.0,
                "debit": debit,
                "credit": credit,
                "description": row.get("Description", ""),
                "reference": row.get("Reference", ""),
            })
            continue

        if quantity > 0 and credit > 0:
            position["sharesSold"] += quantity
            position["saleProceeds"] += credit
            transaction_type = "sell"
            position["transactions"].append({
                "date": row.get("Date", ""),
                "settlementDate": row.get("Settlement Date", ""),
                "type": transaction_type,
                "quantity": quantity,
                "price": parse_money(row.get("Price", "")) if row.get("Price") else 0.0,
                "debit": debit,
                "credit": credit,
                "description": row.get("Description", ""),
                "reference": row.get("Reference", ""),
            })
            continue

        unclassified_rows.append({
            "date": row.get("Date", ""),
            "settlementDate": row.get("Settlement Date", ""),
            "symbol": symbol,
            "description": row.get("Description", ""),
            "quantity": quantity,
            "debit": debit,
            "credit": credit,
        })

    report_rows = []
    for position in positions.values():
        symbol = str(position["symbol"])
        price_info = prices.get(symbol, PriceInfo(0.0, "", "", "Missing latest price"))
        purchase_cost = float(position["purchaseCost"])
        dividend_return = float(position["dividends"])
        net_shares = float(position["sharesBought"]) - float(position["sharesSold"])
        has_price = not price_info.error
        current_value = net_shares * price_info.price if has_price else 0.0
        share_price_return = float(position["saleProceeds"]) + current_value - purchase_cost
        total_return = share_price_return + dividend_return
        dividend_return_pct = (dividend_return / purchase_cost * 100) if purchase_cost else 0.0
        share_price_return_pct = (share_price_return / purchase_cost * 100) if purchase_cost else 0.0
        total_return_pct = (total_return / purchase_cost * 100) if purchase_cost else 0.0

        report_rows.append({
            **position,
            "netShares": net_shares,
            "hasPrice": has_price,
            "latestPrice": price_info.price,
            "latestPriceDate": price_info.price_date,
            "priceError": price_info.error,
            "fetchedAtUtc": price_info.fetched_at_utc,
            "currentValue": current_value,
            "dividendReturn": dividend_return,
            "dividendReturnPct": dividend_return_pct,
            "sharePriceReturn": share_price_return,
            "sharePriceReturnPct": share_price_return_pct,
            "totalReturn": total_return,
            "totalReturnPct": total_return_pct,
        })

    report_rows.sort(key=lambda row: row["totalReturn"], reverse=True)
    price_missing_symbols = [str(row["symbol"]) for row in report_rows if not row["hasPrice"]]
    invested_with_prices = sum(float(row["purchaseCost"]) for row in report_rows if row["hasPrice"])
    fetched_at_values = sorted({str(row["fetchedAtUtc"]) for row in report_rows if row["fetchedAtUtc"]})
    fetched_at_utc = fetched_at_values[-1] if fetched_at_values else ""
    summary = {
        "positions": len(report_rows),
        "invested": sum(float(row["purchaseCost"]) for row in report_rows),
        "investedWithPrices": invested_with_prices,
        "proceeds": sum(float(row["saleProceeds"]) for row in report_rows),
        "dividends": sum(float(row["dividends"]) for row in report_rows),
        "currentValue": sum(float(row["currentValue"]) for row in report_rows if row["hasPrice"]),
        "dividendReturn": sum(float(row["dividendReturn"]) for row in report_rows),
        "sharePriceReturn": sum(float(row["sharePriceReturn"]) for row in report_rows if row["hasPrice"]),
        "totalReturn": sum(float(row["totalReturn"]) for row in report_rows if row["hasPrice"]),
        "fetchedAtUtc": fetched_at_utc,
    }
    summary["totalReturnPct"] = (summary["totalReturn"] / invested_with_prices * 100) if invested_with_prices else 0.0

    if price_missing_symbols:
        LOGGER.warning("Missing live prices for symbols: %s", ", ".join(price_missing_symbols))

    if unclassified_rows:
        LOGGER.warning("Excluded %s unclassified transaction row(s)", len(unclassified_rows))
        for row in unclassified_rows:
            LOGGER.warning(
                "Unclassified row | date=%s settlement=%s symbol=%s quantity=%s debit=%s credit=%s description=%s",
                row["date"],
                row["settlementDate"],
                row["symbol"],
                row["quantity"],
                row["debit"],
                row["credit"],
                row["description"],
            )

    return {
        "summary": summary,
        "rows": report_rows,
        "prices": {symbol: asdict(info) for symbol, info in prices.items()},
    }


class ReportHandler(SimpleHTTPRequestHandler):
    REPORT_PAGE = "/investment_returns_report.html"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/report":
            self.serve_report()
            return
        if parsed.path == self.REPORT_PAGE:
            self.path = parsed.path
            super().do_GET()
            return
        self.send_error(404, "Not found")

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == self.REPORT_PAGE:
            self.path = parsed.path
            super().do_HEAD()
            return
        self.send_error(404, "Not found")

    def list_directory(self, path: str):  # type: ignore[override]
        self.send_error(403, "Directory listing is disabled")
        return None

    def serve_report(self) -> None:
        try:
            rows = read_transactions()
            prices = fetch_latest_prices(get_symbols(rows))
            payload = json.dumps(build_report(rows, prices)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = "127.0.0.1"
    port = 10120
    server = ThreadingHTTPServer((host, port), ReportHandler)
    LOGGER.info("Serving report at http://%s:%s/investment_returns_report.html", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
