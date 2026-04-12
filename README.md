# FX1 — USD Factor Residual Mean-Reversion Strategy

**NUS FT5010 Final-Term Project**

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements_fx.txt

# 2. Run the interactive entry point
python run.py
```

`run.py` presents a menu: fetch data, run backtest, start live trader, or open the dashboard.

---

## OANDA Practice Account Credentials

| Field | Value |
|---|---|
| Account ID | `101-003-38807757-001` |
| API Key | `bc92c0fdaf6522191c5cca914493a283-bfffc8fb47d90822ad1ba0e5274a3ab8` |
| Environment | `practice` (paper trading — no real money) |
| Base URL | `https://api-fxpractice.oanda.com` |

> **Note for examiner**: Credentials are hardcoded in `config/config.yaml`. Please do not revoke or modify the API key before the end of the assessment period.

---

## Live Dashboard (Already Running)

The strategy is deployed on an Azure VM and running live:

**http://135.235.139.80:8000/app**

The dashboard shows in real-time:
- Account balance, NAV, unrealised/realised P&L
- Equity curve with drawdown shading
- Regime classification (HMM: Idiosyncratic / Transitional / Macro)
- Open positions and trade log
- Risk metrics: Sharpe, Sortino, Calmar, Max Drawdown, Skewness, Kurtosis, VaR 95%, Profit Factor
- P&L distribution chart
- Kill switch (closes all open positions instantly)

---

## Strategy Overview

FX1 trades **mean-reversion** in the idiosyncratic (non-USD-factor) residuals of 7 G10 currency pairs on M30 (30-minute) bars.

### Instruments
`EUR_USD`, `GBP_USD`, `AUD_USD`, `NZD_USD`, `USD_CAD`, `USD_CHF`, `USD_JPY`

### Signal Pipeline

```
Raw M30 OANDA bars (5 years, ~62k bars/pair)
    │
    ├── Rolling PCA (window=60)         — extract common USD factor
    ├── Kalman filter                   — dynamic factor loadings per pair
    ├── OU z-score (window=720 bars)    — measure residual deviation from mean
    ├── Session demean (UTC 0–12)       — remove time-of-day drift
    │
    ├─── FILTERS (all must pass) ───────────────────────────────────────
    │   ├── |z| > 1.5σ                 — entry threshold
    │   ├── Hawkes decay gate           — only enter as spread spikes decay
    │   ├── Cross-pair correlation      — block correlated simultaneous signals
    │   ├── Macro guard                 — block if ≥3 pairs have spiked spreads
    │   └── Spread check               — current spread < 1.5× 100-bar median
    │
    └── ORDER EXECUTION ────────────────────────────────────────────────
        ├── HAR-RV vol forecast         — scale position size to volatility
        ├── Vol-adjusted leverage       — lev = min(vol_ref/har_rv, 50×)
        ├── Market order via OANDA      — immediate fill, no GTD limit risk
        ├── SL: z = 2.2σ away          — stop if residual extends further
        └── TP: z = 0.5σ               — take profit on mean reversion
```

### HMM Regime (metadata only)
A 3-state Hidden Markov Model classifies each bar as `idiosyncratic` / `transitional` / `macro` based on cross-pair dispersion and Hawkes intensity. This is displayed on the dashboard but is **not** a hard entry filter — it was found to be unreliable out-of-sample.

### Risk Parameters
| Parameter | Value |
|---|---|
| Max leverage | 50× (vol-adjusted, typically 20–40×) |
| Margin per trade | SGD 200,000 |
| Max open trades | 2 simultaneously |
| Cash buffer | SGD 50,000 reserved |
| Daily drawdown kill | 3% |

---

## Backtest Results (Out-of-Sample)

Test period: **Jun 2024 – Mar 2026** (last 35% of data, ~1.78 years)

Benchmarks over the same period:
- **EUR/USD Buy-and-Hold**: long 1 unit EUR/USD (1.0738 → 1.1558, +4.2% ann.)
- **Risk-Free Rate**: US 3-Month T-Bill yield ~5.25% annualised (prevailing SOFR over test period)

| Metric | FX1 Strategy | EUR/USD B&H | Risk-Free (T-Bill) |
|---|---|---|---|
| Ann. Return | **+14.4%** | +4.2% | ~5.25% |
| Sharpe Ratio | **1.99** | 0.55 | — |
| Max Drawdown | **-3.4%** | -9.1% | — |
| Win Rate | 56.4% | — | — |
| Profit Factor | 1.74 | — | — |
| Total Trades | 117 | — | — |
| Avg Leverage | ~39× | — | — |

FX1 delivers **3.4× the annualised return** of EUR/USD buy-and-hold (+14.4% vs +4.2%), with **3.6× higher Sharpe** and **2.7× lower drawdown**.

Run the backtest yourself: `python run.py` → option `[2]`

---

## Project Structure

```
fx_oanda/
├── run.py                    ← START HERE (interactive entry point)
├── config/config.yaml        ← all parameters + OANDA credentials
├── notebooks/
│   └── FX1_deliverable.ipynb ← backtesting notebook (submission item 2)
├── backend/
│   └── api.py                ← FastAPI server, WebSocket broadcast, metrics
├── runtime/
│   └── live_trader.py        ← live trading loop (bar-by-bar execution)
├── strategy/
│   └── pipeline.py           ← full signal pipeline (PCA→Kalman→OU→filters)
├── backtest/
│   └── engine.py             ← event-based backtester
├── signals/                  ← hawkes_spread, kalman_loadings, ou_zscore, pca_factor
├── filters/                  ← hmm_regime, macro_guard, ortho (correlation filter)
├── models/                   ← har_rv (volatility forecasting), kelly_sizer
├── execution/
│   └── oanda_exec.py         ← OANDA REST API wrapper (place/close orders)
├── data/
│   └── fetch_oanda.py        ← downloads and caches M30 bars
├── frontend/                 ← React dashboard (Vite + Plotly + Tailwind)
└── cli.py                    ← command-line interface (used by run.py)
```

---

## Dashboard Note

The requirement specifies Python Dash. We implemented the dashboard using **React + FastAPI** instead, for one reason: real-time WebSocket streaming. Python Dash's polling model updates every N seconds via HTTP, which causes visible lag. Our WebSocket approach pushes updates every 10 seconds and handles the kill switch as an immediate server-side event.

The `backend/` folder contains all Python dashboard logic (FastAPI routes, WebSocket broadcaster, metrics engine). This can be considered the "dashboard code" submission.

All required dashboard features are covered:
- ✅ Strategy description and status
- ✅ Current PnL and equity
- ✅ Open positions
- ✅ Risk metrics
- ✅ Kill switch (closes all open trades via OANDA API)
- ✅ Benchmark comparison (EUR/USD buy-and-hold shown in backtest output)
- ✅ Visualisations (equity curve, P&L distribution, regime panel, pair grid)

---

## Running Locally vs Azure

The system is already running on Azure (http://135.235.139.80:8000/app).

To run locally:
1. `pip install -r requirements_fx.txt`
2. `python run.py` → option `[1]` to fetch data (first time only, ~5 min)
3. `python run.py` → option `[4]` to start the local dashboard

Node.js is required to build the frontend locally (`npm` must be on PATH). If not available, use option `[5]` to open the deployed Azure dashboard directly.
