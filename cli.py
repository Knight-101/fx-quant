from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fx_oanda.backtest.engine import FX1Backtester
from fx_oanda.backtest.metrics import write_backtest_artifacts
from fx_oanda.config.loader import ensure_dirs, load_config
from fx_oanda.data.fetch_oanda import fetch_all, load_cache
from fx_oanda.runtime.live_trader import FX1LiveTrader
from fx_oanda.strategy.pipeline import build_candidate_signals, build_strategy_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def cmd_fetch(args) -> None:
    cfg = load_config(args.config)
    ensure_dirs(cfg)
    fetch_all(cfg, force=args.force)
    print("Fetched and cached OANDA data.")


def _benchmark_eurusd(state, train_end_time: pd.Timestamp) -> dict:
    """Buy-and-hold EUR/USD over the test period as a benchmark for comparison."""
    prices = state.prices.get("EUR_USD", pd.DataFrame())
    if prices.empty:
        return {}
    test_prices = prices[prices.index > train_end_time]["close"].dropna()
    if len(test_prices) < 2:
        return {}
    bnh_return = float(test_prices.iloc[-1] / test_prices.iloc[0] - 1.0)
    daily = test_prices.resample("1D").last().dropna().pct_change().dropna()
    bnh_sharpe = float(daily.mean() / daily.std() * (252 ** 0.5)) if daily.std() > 0 else 0.0
    rolling_max = test_prices.cummax()
    bnh_dd = float(((test_prices - rolling_max) / rolling_max).min())
    return {
        "bnh_return": round(bnh_return, 4),
        "bnh_sharpe": round(bnh_sharpe, 4),
        "bnh_max_drawdown": round(bnh_dd, 4),
    }


def cmd_backtest(args) -> None:
    cfg = load_config(args.config)
    ensure_dirs(cfg)
    data = load_cache(cfg)

    state = build_strategy_state(data, cfg)
    train_end_time = state.train_end_time

    print(f"[backtest] Train period: up to {train_end_time}")
    print(f"[backtest] Test  period: {train_end_time} → {state.returns.index[-1]}")

    all_signals = build_candidate_signals(state, cfg)
    if all_signals.empty:
        print("[backtest] No candidate signals generated. Exiting.")
        return

    test_signals = all_signals[all_signals.index > train_end_time].copy()
    print(f"[backtest] Candidate signals — all: {len(all_signals)}, test: {len(test_signals)}")

    if test_signals.empty:
        print("[backtest] No test-period signals. Try lowering z_entry_weak or train_fraction.")
        return

    print(f"[backtest] Running backtest on {len(test_signals)} test signals")
    result = FX1Backtester(cfg).run(test_signals, state.prices)
    run_dir = Path(cfg["paths"]["backtest_dir"]) / datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    summary = write_backtest_artifacts(run_dir, result, test_signals, state.diagnostics)

    benchmark = _benchmark_eurusd(state, train_end_time)
    print(json.dumps({"run_dir": str(run_dir), **summary["metrics"], **benchmark}, indent=2))

    if benchmark:
        print("\n── Strategy vs Benchmark (EUR/USD Buy-and-Hold) ──────────────")
        print(f"  Total Return:  {summary['metrics']['total_return']:+.2%}  vs  {benchmark['bnh_return']:+.2%}")
        print(f"  Sharpe Ratio:  {summary['metrics']['sharpe']:.2f}        vs  {benchmark['bnh_sharpe']:.2f}")
        print(f"  Max Drawdown:  {summary['metrics']['max_drawdown']:.2%}      vs  {benchmark['bnh_max_drawdown']:.2%}")
        print("────────────────────────────────────────────────────────────────")


def _next_bar_close(granularity_min: int = 30, buffer_sec: int = 60) -> pd.Timestamp:
    """Return the UTC timestamp of the next M30 bar close + buffer."""
    now = pd.Timestamp.utcnow()
    minutes_past = now.minute % granularity_min
    wait_min = (granularity_min - minutes_past) % granularity_min or granularity_min
    return (now + pd.Timedelta(minutes=wait_min)).replace(second=buffer_sec, microsecond=0)


def cmd_live(args) -> None:
    """Run live trader on every M30 bar close (loops forever)."""
    cfg = load_config(args.config)

    if not cfg["oanda"].get("api_key"):
        log.error("OANDA_API_TOKEN not set. Export it before running live.")
        raise SystemExit(1)
    if not cfg["oanda"].get("account_id"):
        log.error("OANDA_ACCOUNT_ID not set. Export it before running live.")
        raise SystemExit(1)

    log.info("Starting FX1 live trader (practice account: %s)", cfg["oanda"].get("account_id"))
    log.info("Press Ctrl-C to stop gracefully.")

    trader = FX1LiveTrader(args.config)

    # Run immediately on startup, then loop on bar close
    run_count = 0
    while True:
        try:
            now = pd.Timestamp.utcnow()
            log.info("─── Bar %d at %s UTC ───", run_count + 1, now.strftime("%Y-%m-%d %H:%M"))
            snapshot = trader.run_bar()
            log.info(
                "regime=%-12s  open_trades=%d  signals=%d",
                snapshot.regime,
                len(snapshot.open_trades),
                len(snapshot.recent_signals),
            )
            run_count += 1
        except KeyboardInterrupt:
            log.info("Interrupted — exiting cleanly.")
            break
        except Exception as exc:
            log.error("run_bar() error: %s", exc, exc_info=True)

        # Sleep until next M30 bar close
        next_run = _next_bar_close(granularity_min=30, buffer_sec=60)
        sleep_sec = max((next_run - pd.Timestamp.utcnow()).total_seconds(), 0)
        log.info("Sleeping %.0f s until next bar (%s UTC)…", sleep_sec, next_run.strftime("%H:%M:%S"))
        time.sleep(sleep_sec)


def cmd_live_once(args) -> None:
    """Run a single bar cycle (useful for cron or manual testing)."""
    trader = FX1LiveTrader(args.config)
    snapshot = trader.run_bar()
    print(json.dumps(vars(snapshot), indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FX1 OANDA strategy")
    parser.add_argument("--config", type=str, default="")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch/refresh OANDA M30 data")
    fetch_p.add_argument("--force", action="store_true")
    fetch_p.set_defaults(func=cmd_fetch)

    bt_p = sub.add_parser("backtest", help="Run walk-forward backtest")
    bt_p.set_defaults(func=cmd_backtest)

    live_p = sub.add_parser("live", help="Run live trader loop (executes on every M30 bar close)")
    live_p.set_defaults(func=cmd_live)

    once_p = sub.add_parser("live-once", help="Run a single bar cycle and exit")
    once_p.set_defaults(func=cmd_live_once)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
