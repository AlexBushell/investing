# Infrastructure Monitoring

Local tooling for reviewing per-investment returns on a small infrastructure portfolio, including dividends and live Yahoo Finance prices.

## Files

- [infrastructure_investments.csv](</c:/dev/investing/Infra Monitoring/infrastructure_investments.csv>)  
  Broker export used as the transaction ledger. The report reads this file on every page load.

- [serve_investment_report.py](</c:/dev/investing/Infra Monitoring/serve_investment_report.py>)  
  Small local HTTP server that reads the ledger, fetches live prices with `yfinance`, calculates returns, and serves the report page plus `/api/report`.

- [investment_returns_report.html](</c:/dev/investing/Infra Monitoring/investment_returns_report.html>)  
  Local browser UI that auto-loads the latest report from the server. No file picker is required.

- [fetch_latest_prices.py](</c:/dev/investing/Infra Monitoring/fetch_latest_prices.py>)  
  Optional helper for generating a standalone `latest_prices.csv`, but it is not needed for the normal report flow.

## What The Report Calculates

For each symbol, the report currently computes:

- total shares bought
- total shares sold
- net shares still held
- purchase cost
- sale proceeds
- dividends received
- current value using the latest Yahoo close, converted from London-listed GBp quotes into GBP
- total return: `sale proceeds + dividends + current value - purchase cost`

## Current Classification Rules

The ledger is interpreted with these rules:

- dividend rows: `Description` starts with `Div`
- buy rows: `Quantity > 0` and `Debit > 0`
- sell rows: `Quantity > 0` and `Credit > 0`
- rows with `Symbol = n/a` are ignored for investment return calculations

Rows that do not match those rules are excluded from totals and logged by the server for review.

## Live Report Workflow

These commands assume Git Bash on Windows and a local virtual environment in this folder.

1. Create and activate the virtual environment:

```bash
cd "/c/dev/investing/Infra Monitoring"
python -m venv .venv
source .venv/Scripts/activate
```

2. Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install yfinance pandas
```

3. Start the local server:

```bash
python serve_investment_report.py
```

4. Open the report in your browser:

```text
http://127.0.0.1:8000/investment_returns_report.html
```

The page will automatically:

- read `infrastructure_investments.csv`
- fetch live Yahoo prices
- render the latest per-investment return summary

## Logging

The UI is intentionally minimal. Warnings and review items are written to the server logs instead, including:

- missing Yahoo prices for a symbol
- transaction rows that do not match the current buy, sell, or dividend rules

## Warnings And Limitations

- The README commands assume `python` is available in Git Bash. If your machine uses `python3` instead, substitute that in the commands above.
- Missing Yahoo prices are treated as unknown, not zero. Portfolio totals exclude symbols with missing live prices.
- Yahoo `.L` prices are returned in pence, so the scripts convert them to pounds before calculating values and returns.
- The portfolio return percentage is based only on positions with a known current price.
- The report is symbol-level performance, not a tax-lot engine.
- It does not currently model fees, taxes, stamp duty, or return-of-capital adjustments unless they fit the current row rules.
- Yahoo prices are based on recent daily history, so the value shown is effectively latest available close rather than a streaming quote.

## Expected Input Symbols

The current Yahoo mapping covers:

- `BSIF`
- `FGEN`
- `GCP`
- `HICL`
- `NESF`
- `TRIG`
- `UKW`

If new holdings appear, update the `YAHOO_TICKERS` mapping in [serve_investment_report.py](</c:/dev/investing/Infra Monitoring/serve_investment_report.py>) and [fetch_latest_prices.py](</c:/dev/investing/Infra Monitoring/fetch_latest_prices.py>).
