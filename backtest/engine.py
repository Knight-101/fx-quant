from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fx_oanda.models.kelly_sizer import compute_position_size, vol_adjusted_leverage


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    summary: dict


class FX1Backtester:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def run(
        self,
        signals_df: pd.DataFrame,
        price_data: dict[str, pd.DataFrame],
        account_balance: float = 100_000.0,
    ) -> BacktestResult:
        balance = float(account_balance)
        max_leverage    = float(self.cfg["risk"].get("max_leverage", 50.0))
        pair_margin_cap = float(self.cfg["risk"].get("pair_margin_cap", 10_000.0))
        cash_buffer     = float(self.cfg["risk"].get("cash_buffer", 30_000.0))
        vol_ref         = float(self.cfg["risk"].get("vol_ref", 0.015))
        max_open        = int(self.cfg["risk"]["max_open_trades"])
        entry_timeout   = int(self.cfg["execution"].get("entry_timeout_bars", 2))
        time_stop       = int(self.cfg["execution"].get("time_stop_bars", 8))
        assume_fills    = bool(self.cfg["execution"].get("assume_all_fills", True))

        # active_positions[pair] = {exit_time, margin_committed}
        active_positions: dict[str, dict] = {}

        trades: list[dict] = []
        equity_curve: list[dict] = []

        for timestamp, signal in signals_df.sort_index().iterrows():
            # Release positions that have already exited
            for pair_key in list(active_positions.keys()):
                if active_positions[pair_key]["exit_time"] <= timestamp:
                    del active_positions[pair_key]

            pair = signal["pair"]
            if len(active_positions) >= max_open or pair in active_positions:
                continue

            # Cash-buffer guard
            total_deployed = sum(p["margin_committed"] for p in active_positions.values())
            if total_deployed + pair_margin_cap > balance - cash_buffer:
                continue

            prices = price_data.get(pair, pd.DataFrame())
            if prices.empty or timestamp not in prices.index:
                continue
            start_loc = prices.index.get_loc(timestamp)

            entry_price = float(signal["entry_price"])
            direction   = int(signal["direction"])
            spread      = float(signal.get("spread", 0.0))

            # --- Limit order entry: post at bid (long) or ask (short) ---
            # limit_price = mid - direction × 0.5 × spread
            # (long buys at bid below mid; short sells at ask above mid)
            limit_price = entry_price - direction * 0.5 * spread

            if assume_fills:
                # Fill at limit price on the very next bar (no fill-check needed)
                next_bar = prices.iloc[start_loc + 1 : start_loc + 2]
                if next_bar.empty:
                    continue
                fill_price = limit_price
                fill_time  = next_bar.index[0]
            else:
                # Try to fill within entry_timeout_bars
                entry_window = prices.iloc[start_loc + 1 : start_loc + 1 + entry_timeout]
                fill_price = None
                fill_time  = None
                for bar_time, bar in entry_window.iterrows():
                    if direction == 1 and float(bar["low"]) <= limit_price:
                        fill_price = limit_price
                        fill_time  = bar_time
                        break
                    if direction == -1 and float(bar["high"]) >= limit_price:
                        fill_price = limit_price
                        fill_time  = bar_time
                        break

                if fill_price is None:
                    continue

            # --- Vol-adjusted leverage ---
            har_rv = float(signal.get("har_rv", vol_ref))
            lev    = vol_adjusted_leverage(har_rv, vol_ref, max_leverage)

            # --- Position size ---
            units = compute_position_size(pair_margin_cap, lev, fill_price) * direction
            if abs(units) < 1:
                continue

            # Simulate bar-by-bar exit from fill_time onward
            fill_loc = prices.index.get_loc(fill_time)
            future   = prices.iloc[fill_loc + 1 : fill_loc + 1 + time_stop]
            if future.empty:
                continue

            exit_price  = float(future.iloc[-1]["close"])
            exit_time   = future.index[-1]
            exit_reason = "time"
            for bar_time, bar in future.iterrows():
                price = float(bar["close"])
                if direction == 1 and price >= float(signal["tp_price"]):
                    exit_price, exit_time, exit_reason = float(signal["tp_price"]), bar_time, "tp"
                    break
                if direction == 1 and price <= float(signal["sl_price"]):
                    exit_price, exit_time, exit_reason = float(signal["sl_price"]), bar_time, "sl"
                    break
                if direction == -1 and price <= float(signal["tp_price"]):
                    exit_price, exit_time, exit_reason = float(signal["tp_price"]), bar_time, "tp"
                    break
                if direction == -1 and price >= float(signal["sl_price"]):
                    exit_price, exit_time, exit_reason = float(signal["sl_price"]), bar_time, "sl"
                    break

            # PnL: entry at limit fill_price; exit is a market order (pay half-spread)
            gross_pnl   = (exit_price - fill_price) * units
            exit_spread = 0.5 * spread * abs(units)   # only exit half-spread (entry was free)
            net_pnl     = gross_pnl - exit_spread
            balance    += net_pnl

            notional   = abs(units) * fill_price
            actual_lev = notional / pair_margin_cap

            active_positions[pair] = {
                "exit_time":        exit_time,
                "margin_committed": pair_margin_cap,
            }
            trades.append(
                {
                    "entry_time":   timestamp,
                    "fill_time":    fill_time,
                    "exit_time":    exit_time,
                    "pair":         pair,
                    "direction":    direction,
                    "entry_price":  entry_price,
                    "fill_price":   fill_price,
                    "exit_price":   exit_price,
                    "units":        int(units),
                    "notional":     notional,
                    "margin":       pair_margin_cap,
                    "leverage":     actual_lev,
                    "har_rv":       har_rv,
                    "z_score":      float(signal["z_score"]),
                    "spread":       spread,
                    "pnl":          net_pnl,
                    "exit_reason":  exit_reason,
                    "balance":      balance,
                }
            )
            equity_curve.append({"time": exit_time, "balance": balance})

        trades_df = pd.DataFrame(trades)
        equity_df  = pd.DataFrame(equity_curve)
        return BacktestResult(
            trades=trades_df,
            equity_curve=equity_df,
            summary=self.metrics(trades_df, equity_df, account_balance),
        )

    def metrics(
        self,
        trades_df: pd.DataFrame,
        equity_df: pd.DataFrame,
        initial_balance: float,
    ) -> dict:
        if trades_df.empty:
            return {
                "total_trades": 0, "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "net_pnl": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "total_return": 0.0,
                "avg_leverage": 0.0, "avg_notional": 0.0, "fill_rate": 0.0,
            }
        wins   = trades_df[trades_df["pnl"] > 0]
        losses = trades_df[trades_df["pnl"] <= 0]
        if equity_df.empty:
            equity_df = pd.DataFrame([{
                "time": trades_df["exit_time"].iloc[-1],
                "balance": initial_balance + trades_df["pnl"].sum(),
            }])
        equity   = equity_df.set_index("time")["balance"].sort_index()
        drawdown = (equity - equity.cummax()) / equity.cummax().replace(0.0, np.nan)
        pnl_std  = float(trades_df["pnl"].std()) if len(trades_df) > 1 else 0.0
        # Annualize per-trade Sharpe using actual trades/year
        trade_years = max((trades_df["exit_time"].max() - trades_df["entry_time"].min()).days / 365.25, 1e-6)
        trades_per_year = len(trades_df) / trade_years
        sharpe   = (
            float(trades_df["pnl"].mean()) / pnl_std * math.sqrt(trades_per_year)
            if pnl_std > 1e-12 else 0.0
        )
        loss_sum = float(losses["pnl"].sum()) if len(losses) else 0.0
        profit_factor = (
            abs(float(wins["pnl"].sum()) / loss_sum) if loss_sum != 0.0 else float("inf")
        )
        return {
            "total_trades":  int(len(trades_df)),
            "win_rate":      float((trades_df["pnl"] > 0).mean()),
            "avg_win":       float(wins["pnl"].mean()) if len(wins) else 0.0,
            "avg_loss":      float(losses["pnl"].mean()) if len(losses) else 0.0,
            "profit_factor": float(profit_factor),
            "net_pnl":       float(trades_df["pnl"].sum()),
            "sharpe":        float(sharpe),
            "max_drawdown":  float(drawdown.min()) if not drawdown.empty else 0.0,
            "total_return":  float(equity.iloc[-1] / initial_balance - 1.0),
            "avg_leverage":  float(trades_df["leverage"].mean()) if "leverage" in trades_df else 0.0,
            "avg_notional":  float(trades_df["notional"].mean()) if "notional" in trades_df else 0.0,
        }
