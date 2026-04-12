from __future__ import annotations

import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent
EQUITY_CSV = ROOT / "backtest/results/run_20260412_112503/equity_curve.csv"
EURUSD_PQ  = ROOT / "data/cache/EUR_USD.parquet"
OUT_PNG    = ROOT / "backtest/results/strategy_vs_eurusd.png"

INIT = 500_000.0

# ── Style ──────────────────────────────────────────────────────────────────────
BG      = "#0f1117"
AX      = "#1a1d27"
GRID    = "#2a2d3d"
TXT     = "#c0c4d0"
STRAT_C = "#00aaff"
EUR_C   = "#ff9900"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor":   AX,
    "axes.edgecolor":   GRID,
    "axes.labelcolor":  TXT,
    "xtick.color":      TXT,
    "ytick.color":      TXT,
    "text.color":       TXT,
    "grid.color":       GRID,
    "grid.linewidth":   0.6,
    "legend.facecolor": AX,
    "legend.edgecolor": GRID,
    "font.family":      "monospace",
    "font.size":        9,
})

# ── Load strategy equity curve ─────────────────────────────────────────────────
eq = pd.read_csv(EQUITY_CSV, parse_dates=["time"])
eq["time"] = pd.to_datetime(eq["time"], utc=True)
eq = eq.sort_values("time").drop_duplicates("time")

t0 = eq["time"].iloc[0] - pd.Timedelta(hours=2)
eq = pd.concat([pd.DataFrame({"time": [t0], "balance": [INIT]}), eq], ignore_index=True)

strat_start = eq["time"].iloc[0]
strat_end   = eq["time"].iloc[-1]
years       = (strat_end - strat_start).days / 365.25

eq["cum_ret"] = (eq["balance"] / INIT - 1) * 100
eq["dd"]      = (eq["balance"] - eq["balance"].cummax()) / eq["balance"].cummax() * 100

# ── Load EUR/USD ───────────────────────────────────────────────────────────────
eur = pd.read_parquet(EURUSD_PQ)[["close"]]
eur = eur[(eur.index >= strat_start) & (eur.index <= strat_end)].copy()
eur["cum_ret"] = (eur["close"] / eur["close"].iloc[0] - 1) * 100
eur["dd"]      = (eur["close"] - eur["close"].cummax()) / eur["close"].cummax() * 100

# ── Key numbers ────────────────────────────────────────────────────────────────
strat_total  = eq["cum_ret"].iloc[-1]
strat_ann    = ((1 + strat_total / 100) ** (1 / years) - 1) * 100
strat_maxdd  = eq["dd"].min()
strat_sharpe = 1.99

eur_total  = eur["cum_ret"].iloc[-1]
eur_ann    = ((1 + eur_total / 100) ** (1 / years) - 1) * 100
eur_maxdd  = eur["dd"].min()
eur_daily  = eur["close"].resample("1D").last().dropna().pct_change().dropna()
eur_sharpe = float(eur_daily.mean() / eur_daily.std() * 252 ** 0.5) if eur_daily.std() > 0 else 0

# ── Figure: 3 rows, 1 column (full width throughout) ──────────────────────────
fig = plt.figure(figsize=(14, 10))
gs  = fig.add_gridspec(
    3, 1,
    height_ratios=[3.2, 1.8, 1.8],
    hspace=0.32,
    left=0.07, right=0.97, top=0.92, bottom=0.06,
)
ax_eq   = fig.add_subplot(gs[0])
ax_dd   = fig.add_subplot(gs[1], sharex=ax_eq)
ax_roll = fig.add_subplot(gs[2])

# ── Panel 1: Cumulative return (full width) ────────────────────────────────────
ax_eq.plot(eq["time"],  eq["cum_ret"],  color=STRAT_C, lw=2.0, label="FX1 Strategy (SGD 500k)")
ax_eq.plot(eur.index,   eur["cum_ret"], color=EUR_C,   lw=1.4, ls="--", label="EUR/USD Buy-and-Hold")
ax_eq.fill_between(eq["time"], 0, eq["cum_ret"], alpha=0.08, color=STRAT_C)
ax_eq.axhline(0, color="#ffffff22", lw=0.8, ls=":")

ax_eq.set_ylabel("Cumulative Return (%)")
ax_eq.set_title("FX1 Strategy vs EUR/USD Buy-and-Hold", fontsize=12, fontweight="bold", color="white")
ax_eq.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
ax_eq.legend(loc="upper left", fontsize=9.5, bbox_to_anchor=(0.01, 0.72))
ax_eq.grid(True, alpha=0.35)
plt.setp(ax_eq.xaxis.get_majorticklabels(), visible=False)

# ── Panel 2: Drawdown (full width) ────────────────────────────────────────────
ax_dd.fill_between(eq["time"], eq["dd"],  0, color=STRAT_C, alpha=0.22, label="Strategy DD")
ax_dd.fill_between(eur.index,  eur["dd"], 0, color=EUR_C,   alpha=0.15, label="EUR/USD DD")
ax_dd.plot(eq["time"], eq["dd"],  color=STRAT_C, lw=1.0)
ax_dd.plot(eur.index,  eur["dd"], color=EUR_C,   lw=0.8, ls="--")
ax_dd.axhline(0, color="#ffffff22", lw=0.8)
ax_dd.set_ylabel("Drawdown (%)")
ax_dd.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax_dd.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.setp(ax_dd.xaxis.get_majorticklabels(), rotation=30, ha="right")
ax_dd.legend(loc="lower left", fontsize=9)
ax_dd.grid(True, alpha=0.35)
plt.setp(ax_dd.xaxis.get_majorticklabels(), visible=False)

# ── Panel 3: Rolling 90-day return (full width) ────────────────────────────────
strat_daily_b = eq.set_index("time")["balance"].resample("1D").last().ffill()
strat_roll    = strat_daily_b.pct_change(90).dropna() * 100
eur_roll      = eur["close"].resample("1D").last().ffill().pct_change(90).dropna() * 100

idx        = strat_roll.index.intersection(eur_roll.index)
strat_roll = strat_roll.loc[idx]
eur_roll   = eur_roll.loc[idx]

ax_roll.plot(strat_roll.index, strat_roll.values, color=STRAT_C, lw=1.5, label="Strategy (90-day rolling)")
ax_roll.plot(eur_roll.index,   eur_roll.values,   color=EUR_C,   lw=1.1, ls="--", label="EUR/USD (90-day rolling)")
ax_roll.fill_between(strat_roll.index, strat_roll.values, 0,
                     where=(strat_roll.values >= 0), color=STRAT_C, alpha=0.12)
ax_roll.fill_between(strat_roll.index, strat_roll.values, 0,
                     where=(strat_roll.values < 0),  color="#ff4444", alpha=0.12)
ax_roll.axhline(0, color="#ffffff22", lw=0.8)
ax_roll.set_ylabel("90-Day Rolling Return (%)")
ax_roll.set_title("Rolling 90-Day Return", fontsize=10, fontweight="bold", color="white")
ax_roll.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
ax_roll.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax_roll.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
plt.setp(ax_roll.xaxis.get_majorticklabels(), rotation=30, ha="right")
ax_roll.legend(loc="upper right", fontsize=9)
ax_roll.grid(True, alpha=0.35)

# ── Suptitle ───────────────────────────────────────────────────────────────────
fig.suptitle(
    f"FX1 Strategy vs EUR/USD  |  {strat_start.strftime('%b %Y')} → {strat_end.strftime('%b %Y')}"
    f"  |  SGD 500k  |  Ann. {strat_ann:.1f}%  Sharpe {strat_sharpe:.2f}  MaxDD {strat_maxdd:.2f}%"
    f"  vs  EUR/USD Ann. {eur_ann:.1f}%  Sharpe {eur_sharpe:.2f}  MaxDD {eur_maxdd:.2f}%",
    fontsize=10, fontweight="bold", color="white", y=0.97,
)

# ── Export CSVs ────────────────────────────────────────────────────────────────
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

# 1. Normalised equity curve (time, strategy_cum_ret_pct, eur_cum_ret_pct)
eur_aligned = eur["cum_ret"].reindex(
    pd.date_range(eur.index.min(), eur.index.max(), freq="30min", tz="UTC"),
    method="ffill"
)
norm_csv = OUT_PNG.parent / "equity_curve_normalised.csv"
norm_df = (
    eq.set_index("time")[["cum_ret"]]
    .rename(columns={"cum_ret": "strategy_cum_ret_pct"})
)
norm_df["eur_usd_cum_ret_pct"] = eur["cum_ret"].reindex(norm_df.index, method="ffill")
norm_df.index.name = "time"
norm_df.to_csv(norm_csv)
print(f"Saved → {norm_csv}")

# 2. Benchmark vs walk-forward backtest summary CSV
bench_csv = OUT_PNG.parent / "benchmark_vs_strategy.csv"
summary_rows = [
    {"metric": "ann_return_pct",    "strategy": round(strat_ann, 4),    "eur_usd_bnh": round(eur_ann, 4)},
    {"metric": "total_return_pct",  "strategy": round(strat_total, 4),  "eur_usd_bnh": round(eur_total, 4)},
    {"metric": "sharpe_ratio",      "strategy": round(strat_sharpe, 4), "eur_usd_bnh": round(eur_sharpe, 4)},
    {"metric": "max_drawdown_pct",  "strategy": round(strat_maxdd, 4),  "eur_usd_bnh": round(eur_maxdd, 4)},
    {"metric": "test_years",        "strategy": round(years, 4),        "eur_usd_bnh": round(years, 4)},
    {"metric": "start_date",        "strategy": str(strat_start.date()), "eur_usd_bnh": str(strat_start.date())},
    {"metric": "end_date",          "strategy": str(strat_end.date()),   "eur_usd_bnh": str(strat_end.date())},
    {"metric": "initial_capital",   "strategy": INIT,                   "eur_usd_bnh": "N/A"},
]
pd.DataFrame(summary_rows).to_csv(bench_csv, index=False)
print(f"Saved → {bench_csv}")

fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
print(f"Saved → {OUT_PNG}")
