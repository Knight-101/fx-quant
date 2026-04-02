"""
Walk-forward cross-validation with expanding train window.

5 folds, each with ~6-month test window:
  Fold 1: train Jan2021–Jun2022,  test Jul2022–Dec2022
  Fold 2: train Jan2021–Dec2022,  test Jan2023–Jun2023
  Fold 3: train Jan2021–Jun2023,  test Jul2023–Dec2023
  Fold 4: train Jan2021–Dec2023,  test Jan2024–Jun2024
  Fold 5: train Jan2021–Jun2024,  test Jul2024–Mar2026  (full current OOS window)

For each fold:
  - build_strategy_state with fold's train_fraction (models trained only on train portion)
  - extract signals in (train_end, test_end] window
  - run backtest with $500k account
  - record metrics + equity curve

Outputs saved to backtest/results/cross_validation/:
  equity_curves.png  — equity curve per fold (relative, day-indexed)
  metrics.png        — bar charts: Ann%, WR, PF, Sharpe, Max DD per fold
  pnl_distribution.png — histogram of all trade PnL across folds
  cumulative.png     — concatenated equity across all folds
  summary.json       — all fold metrics
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from fx_oanda.backtest.engine import FX1Backtester
from fx_oanda.config.loader import ensure_dirs, load_config
from fx_oanda.data.fetch_oanda import load_cache
from fx_oanda.strategy.pipeline import build_candidate_signals, build_strategy_state

# ── Config ────────────────────────────────────────────────────────────────────
ACCOUNT_BALANCE = 500_000
OUT_DIR = Path(__file__).parent / "backtest" / "results" / "cross_validation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Walk-forward fold boundaries (train_end, test_end) as pandas Timestamps.
# Expanding training window; 6-month test slices (last fold runs to data end).
FOLD_BOUNDARIES = [
    ("2022-07-01", "2022-12-31"),
    ("2023-01-01", "2023-06-30"),
    ("2023-07-01", "2023-12-31"),
    ("2024-01-01", "2024-06-30"),
    ("2024-07-01", None),           # None = use full remaining test period
]

COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2"]

# ── Load data once ─────────────────────────────────────────────────────────────
cfg = load_config()
ensure_dirs(cfg)
data = load_cache(cfg)

# Get full date range
_dummy_state = build_strategy_state(data, cfg)
full_index = _dummy_state.returns.index
data_start = full_index[0]
data_end   = full_index[-1]
print(f"Data range: {data_start.date()} → {data_end.date()}  ({len(full_index):,} bars)\n")

# ── Run folds ──────────────────────────────────────────────────────────────────
fold_results: list[dict] = []
all_trades: list[pd.DataFrame] = []

for fold_i, (test_start_str, test_end_str) in enumerate(FOLD_BOUNDARIES, 1):
    test_start = pd.Timestamp(test_start_str, tz="UTC")
    test_end   = pd.Timestamp(test_end_str,   tz="UTC") if test_end_str else data_end

    # Train window: everything before this fold's test_start
    train_mask = full_index < test_start
    n_train = train_mask.sum()
    train_fraction = n_train / len(full_index)
    train_end = full_index[n_train - 1]

    print(f"Fold {fold_i}: train → {train_end.date()}  |  test {test_start.date()} → {test_end.date()}")

    if n_train < 2000:
        print(f"  [skip] too few training bars ({n_train})\n")
        continue

    # Build state with this fold's train_fraction
    fold_cfg = copy.deepcopy(cfg)
    fold_cfg["train_fraction"] = float(train_fraction)

    state = build_strategy_state(data, fold_cfg)
    signals = build_candidate_signals(state, fold_cfg)

    if signals.empty:
        print("  [skip] no signals\n")
        continue

    # Filter to this fold's test window
    test_sigs = signals[
        (signals.index >= test_start) & (signals.index <= test_end)
    ].copy()

    n_sigs = len(test_sigs)
    if n_sigs == 0:
        print(f"  [skip] no signals in test window\n")
        continue

    result = FX1Backtester(fold_cfg).run(
        test_sigs, state.prices, account_balance=ACCOUNT_BALANCE
    )
    m = result.summary
    test_years = (test_end - test_start).days / 365.25
    ann = (((1 + m["total_return"]) ** (1 / max(test_years, 1e-6))) - 1) * 100

    print(f"  signals={n_sigs}  trades={m['total_trades']}  WR={m['win_rate']*100:.1f}%  "
          f"PF={m['profit_factor']:.3f}  ann={ann:.2f}%  DD={m['max_drawdown']*100:.2f}%  "
          f"Sharpe={m['sharpe']:.2f}")

    fold_results.append({
        "fold":         fold_i,
        "train_end":    str(train_end.date()),
        "test_start":   test_start_str,
        "test_end":     str(test_end.date()),
        "test_years":   round(test_years, 2),
        "n_signals":    n_sigs,
        "total_trades": m["total_trades"],
        "win_rate":     round(m["win_rate"] * 100, 1),
        "profit_factor":round(m["profit_factor"], 3),
        "ann_return":   round(ann, 2),
        "max_drawdown": round(m["max_drawdown"] * 100, 2),
        "sharpe":       round(m["sharpe"], 2),
        "net_pnl":      round(m["net_pnl"], 2),
        "equity_curve": result.equity_curve.copy(),
        "trades":       result.trades.copy(),
    })

    if not result.trades.empty:
        t = result.trades.copy()
        t["fold"] = fold_i
        all_trades.append(t)

    print()

if not fold_results:
    print("No folds produced results. Exiting.")
    raise SystemExit(1)

# ── Save summary JSON ──────────────────────────────────────────────────────────
summary = [{k: v for k, v in f.items() if k not in ("equity_curve", "trades")} for f in fold_results]
(OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
print(f"Summary saved → {OUT_DIR / 'summary.json'}\n")

# ── Plotting helpers ───────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor": "#0f1117",
    "axes.facecolor":   "#1a1d27",
    "axes.edgecolor":   "#3a3d4d",
    "axes.labelcolor":  "#c0c4d0",
    "xtick.color":      "#c0c4d0",
    "ytick.color":      "#c0c4d0",
    "text.color":       "#e0e4f0",
    "grid.color":       "#2a2d3d",
    "grid.linewidth":   0.6,
    "legend.facecolor": "#1a1d27",
    "legend.edgecolor": "#3a3d4d",
    "font.size":        10,
})

# ── Plot 1: Per-fold equity curves (relative, day-indexed) ─────────────────────
fig, axes = plt.subplots(
    len(fold_results), 1,
    figsize=(12, 3 * len(fold_results)),
    sharex=False,
)
if len(fold_results) == 1:
    axes = [axes]

fig.suptitle("Walk-Forward Cross-Validation — Per-Fold Equity Curves\n$500k Account",
             fontsize=13, fontweight="bold", y=1.01)

for ax, fr, color in zip(axes, fold_results, COLORS):
    eq = fr["equity_curve"]
    if eq.empty:
        ax.text(0.5, 0.5, "No trades", ha="center", va="center", transform=ax.transAxes)
        continue
    eq = eq.set_index("time")["balance"].sort_index()
    days = [(t - eq.index[0]).days for t in eq.index]
    pct  = (eq / ACCOUNT_BALANCE - 1) * 100

    ax.axhline(0, color="#ffffff33", linewidth=0.8, linestyle="--")
    ax.fill_between(days, pct, 0, where=(pct >= 0), alpha=0.15, color=color)
    ax.fill_between(days, pct, 0, where=(pct < 0),  alpha=0.15, color="#C44E52")
    ax.plot(days, pct, color=color, linewidth=1.8)

    meta = fr
    label = (f"Fold {meta['fold']}  |  test {meta['test_start']} → {meta['test_end']}\n"
             f"Trades={meta['total_trades']}  WR={meta['win_rate']}%  "
             f"PF={meta['profit_factor']}  ann={meta['ann_return']}%  "
             f"DD={meta['max_drawdown']}%  Sharpe={meta['sharpe']}")
    ax.set_title(label, fontsize=9, loc="left", pad=4)
    ax.set_ylabel("Return %")
    ax.set_xlabel("Days into test period")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax.grid(True, alpha=0.4)

plt.tight_layout()
fig.savefig(OUT_DIR / "equity_curves.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved → equity_curves.png")

# ── Plot 2: Metrics comparison bar chart ───────────────────────────────────────
metrics_keys = ["ann_return", "win_rate", "profit_factor", "sharpe", "max_drawdown"]
metric_labels = ["Ann Return %", "Win Rate %", "Profit Factor", "Sharpe", "Max DD %"]
fold_labels = [f"F{fr['fold']}\n{fr['test_start'][:7]}" for fr in fold_results]

fig, axes = plt.subplots(1, 5, figsize=(16, 5))
fig.suptitle("Cross-Validation Metrics per Fold  |  $500k Account",
             fontsize=13, fontweight="bold")

for ax, key, label in zip(axes, metrics_keys, metric_labels):
    vals = [fr[key] for fr in fold_results]
    bar_colors = []
    for v in vals:
        if key == "max_drawdown":
            bar_colors.append("#C44E52" if v < -3 else "#DD8452" if v < -1 else "#55A868")
        elif key in ("ann_return", "win_rate", "profit_factor", "sharpe"):
            bar_colors.append("#55A868" if v > 0 else "#C44E52")
        else:
            bar_colors.append(COLORS[0])

    bars = ax.bar(fold_labels, vals, color=bar_colors, edgecolor="#ffffff22", linewidth=0.5)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{v:.2f}", ha="center", va="bottom" if v >= 0 else "top",
                fontsize=8, color="#e0e4f0")

    ax.axhline(0, color="#ffffff44", linewidth=0.8)
    ax.set_title(label, fontsize=10, fontweight="bold")
    ax.set_xlabel("Fold")
    ax.grid(True, axis="y", alpha=0.3)

plt.tight_layout()
fig.savefig(OUT_DIR / "metrics.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved → metrics.png")

# ── Plot 3: PnL distribution across all folds ──────────────────────────────────
if all_trades:
    all_trades_df = pd.concat(all_trades, ignore_index=True)
    wins   = all_trades_df[all_trades_df["pnl"] > 0]["pnl"]
    losses = all_trades_df[all_trades_df["pnl"] <= 0]["pnl"]

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.suptitle(f"Trade PnL Distribution — All Folds  ({len(all_trades_df)} trades)",
                 fontsize=12, fontweight="bold")

    bins = np.linspace(all_trades_df["pnl"].min(), all_trades_df["pnl"].max(), 40)
    ax.hist(wins,   bins=bins, color="#55A868", alpha=0.8, label=f"Wins ({len(wins)})", edgecolor="#ffffff11")
    ax.hist(losses, bins=bins, color="#C44E52", alpha=0.8, label=f"Losses ({len(losses)})", edgecolor="#ffffff11")
    ax.axvline(0, color="#ffffff55", linewidth=1)
    ax.axvline(all_trades_df["pnl"].mean(), color="#FFD700", linewidth=1.5,
               linestyle="--", label=f"Mean ${all_trades_df['pnl'].mean():,.0f}")

    ax.set_xlabel("Trade PnL ($)")
    ax.set_ylabel("Count")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    plt.tight_layout()
    fig.savefig(OUT_DIR / "pnl_distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → pnl_distribution.png")

# ── Plot 4: Concatenated equity curve across all folds ─────────────────────────
fig, ax = plt.subplots(figsize=(14, 6))
fig.suptitle("Concatenated Walk-Forward Equity  |  $500k Account",
             fontsize=12, fontweight="bold")

cursor   = 0.0        # cumulative x-axis (days)
balance  = float(ACCOUNT_BALANCE)
x_ticks  = []
x_labels = []

for fr, color in zip(fold_results, COLORS):
    eq = fr["equity_curve"]
    if eq.empty:
        continue
    eq = eq.set_index("time")["balance"].sort_index()
    days = np.array([(t - eq.index[0]).days for t in eq.index], dtype=float)
    x    = cursor + days
    y    = eq.values

    ax.plot(x, y, color=color, linewidth=1.8,
            label=f"Fold {fr['fold']} ({fr['test_start'][:7]})")
    ax.fill_between(x, balance, y,
                    where=(y >= balance), alpha=0.08, color=color)
    ax.fill_between(x, balance, y,
                    where=(y < balance),  alpha=0.08, color="#C44E52")

    x_ticks.append(cursor + days[0])
    x_labels.append(fr["test_start"][:7])
    cursor = x[-1] + 1
    balance = float(eq.iloc[-1])   # carry forward for shading baseline

ax.axhline(ACCOUNT_BALANCE, color="#ffffff33", linewidth=0.8, linestyle="--",
           label=f"Initial ${ACCOUNT_BALANCE:,}")
ax.set_xlabel("Calendar day (stitched across folds)")
ax.set_ylabel("Portfolio Value ($)")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
ax.set_xticks(x_ticks)
ax.set_xticklabels(x_labels, rotation=30)
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(OUT_DIR / "cumulative.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved → cumulative.png")

# ── Print aggregate summary ────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"CROSS-VALIDATION SUMMARY  ({len(fold_results)} folds, $500k account)")
print(f"{'='*70}")
print(f"{'Fold':5} {'Period':20} {'Trd':4} {'WR%':5} {'PF':6} {'Ann%':7} {'DD%':7} {'Sharpe':7} {'Net PnL':>12}")
print("-"*70)
for fr in fold_results:
    print(f"  {fr['fold']}    {fr['test_start'][:7]}→{fr['test_end'][:7]}  "
          f"{fr['total_trades']:3d}  {fr['win_rate']:4.1f}  {fr['profit_factor']:5.3f}  "
          f"{fr['ann_return']:6.2f}  {fr['max_drawdown']:6.2f}  {fr['sharpe']:6.2f}  "
          f"${fr['net_pnl']:>11,.0f}")

avg_ann = np.mean([fr["ann_return"] for fr in fold_results])
avg_wr  = np.mean([fr["win_rate"]   for fr in fold_results])
avg_pf  = np.mean([fr["profit_factor"] for fr in fold_results])
avg_sh  = np.mean([fr["sharpe"]     for fr in fold_results])
avg_dd  = np.mean([fr["max_drawdown"] for fr in fold_results])
print("-"*70)
print(f"  AVG                      "
      f"      {avg_wr:4.1f}  {avg_pf:5.3f}  {avg_ann:6.2f}  {avg_dd:6.2f}  {avg_sh:6.2f}")
print(f"\nPlots saved to: {OUT_DIR}")
