"""
FX1 — USD Factor Residual Mean-Reversion Strategy
==================================================
NUS FT5010 Final-Term Project

Strategy Summary
----------------
FX1 trades mean-reversion in the idiosyncratic (non-USD-factor) residuals of 7
G10 currency pairs. The pipeline:

  1. Rolling PCA extracts a common USD factor from all pairs every bar.
  2. Kalman filter tracks each pair's dynamic loading onto that factor.
  3. OU z-score measures how far each residual has deviated from its mean.
  4. Session demean removes time-of-day drift (only Asian/London session: UTC 0–12).
  5. Hawkes process gate: only enter when spread-spike activity is *declining*
     (i.e., the market is calming down after a move, not in a fresh spike).
  6. Cross-pair correlation filter: block entry if two signals are too correlated.
  7. Macro guard: block entry if ≥3 pairs simultaneously have elevated spreads
     (indicates a macro event — tariff shock, NFP, central bank, etc.).
  8. HAR-RV model forecasts realised volatility to scale position size.
  9. HMM classifies the regime (idiosyncratic / transitional / macro) — used as
     metadata in the dashboard, NOT as a hard entry filter.
  10. Market orders via OANDA REST API with per-trade SL and TP.

OANDA Practice Account Credentials
------------------------------------
  Account ID : 101-003-38807757-001
  API Key    : bc92c0fdaf6522191c5cca914493a283-bfffc8fb47d90822ad1ba0e5274a3ab8
  Environment: practice (paper trading — no real money)
  Base URL   : https://api-fxpractice.oanda.com

Live Dashboard
--------------
  The live dashboard is deployed on Azure VM at:
  http://135.235.139.80:8000/app

  The dashboard is built with React + FastAPI (real-time WebSocket, 10s updates).
  It shows: PnL, equity curve, open positions, regime, risk metrics, kill switch.
  Note: We chose React+FastAPI over Python Dash to support real-time WebSocket
  streaming — all required dashboard features are covered.

Usage
-----
  python run.py          # interactive menu
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# ── Ensure the repo root is on sys.path so fx_oanda imports work ──────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║          FX1 — USD Factor Residual Mean-Reversion            ║
║          NUS FT5010 Final-Term Project                       ║
╠══════════════════════════════════════════════════════════════╣
║  OANDA Practice Account : 101-003-38807757-001               ║
║  Live Dashboard         : http://135.235.139.80:8000/app     ║
╚══════════════════════════════════════════════════════════════╝
"""

MENU = """
What would you like to do?

  [1] Fetch / refresh OANDA M30 data   (~5 min, downloads 5 years per pair)
  [2] Run walk-forward backtest         (~10 min, trains on 65%, tests on 35%)
  [3] Start live trader locally         (loops on every M30 bar, Ctrl-C to stop)
  [4] Start live dashboard locally      (FastAPI + React, opens browser)
  [5] Open the deployed Azure dashboard (opens http://135.235.139.80:8000/app)
  [q] Quit

Enter choice: """


def check_deps() -> bool:
    """Verify critical packages are installed."""
    missing = []
    for pkg in ["fastapi", "uvicorn", "pandas", "numpy", "hmmlearn", "yaml"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\n[!] Missing packages: {', '.join(missing)}")
        print("    Run:  pip install -r requirements_fx.txt\n")
        return False
    return True


def run_fetch() -> None:
    print("\n[fetch] Downloading M30 OANDA bars for all 7 pairs…")
    print("        This paginates through ~5 years (62k bars/pair). Takes ~5 min.\n")
    subprocess.run([sys.executable, "-m", "fx_oanda.cli", "fetch"], cwd=ROOT.parent, check=False)


def run_backtest() -> None:
    print("\n[backtest] Building strategy state and running walk-forward backtest…")
    print("           Train: first 65% of data (~Jan 2019 – May 2024)")
    print("           Test:  last 35%  of data (~May 2024 – present)")
    print("           Results saved to backtest/results/\n")
    subprocess.run([sys.executable, "-m", "fx_oanda.cli", "backtest"], cwd=ROOT.parent, check=False)


def run_live_trader() -> None:
    print("\n[live] Starting live trader. Executes on every M30 bar close.")
    print("       Press Ctrl-C to stop gracefully.\n")
    try:
        subprocess.run([sys.executable, "-m", "fx_oanda.cli", "live"], cwd=ROOT.parent, check=False)
    except KeyboardInterrupt:
        print("\n[live] Stopped.")


def run_dashboard_local() -> None:
    print("\n[dashboard] Starting local dashboard server…")
    print("            Backend : FastAPI on http://127.0.0.1:8000")
    print("            Frontend: React app at http://127.0.0.1:8000/app")
    print("            Press Ctrl-C to stop.\n")

    frontend_dist = ROOT / "frontend" / "dist"
    if not frontend_dist.exists():
        print("[dashboard] Frontend not built. Building now (requires Node.js)…")
        subprocess.run(["npm", "install"], cwd=ROOT / "frontend", check=False)
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=False)

    # Open browser after a short delay
    def _open():
        time.sleep(3)
        webbrowser.open("http://127.0.0.1:8000/app")

    import threading
    threading.Thread(target=_open, daemon=True).start()

    try:
        subprocess.run(
            [
                sys.executable, "-m", "uvicorn",
                "fx_oanda.backend.api:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--log-level", "info",
            ],
            cwd=ROOT.parent,
            check=False,
        )
    except KeyboardInterrupt:
        print("\n[dashboard] Stopped.")


def open_azure_dashboard() -> None:
    url = "http://135.235.139.80:8000/app"
    print(f"\n[dashboard] Opening {url} in your browser…")
    webbrowser.open(url)


def main() -> None:
    print(BANNER)

    if not check_deps():
        sys.exit(1)

    while True:
        choice = input(MENU).strip().lower()

        if choice == "1":
            run_fetch()
        elif choice == "2":
            run_backtest()
        elif choice == "3":
            run_live_trader()
        elif choice == "4":
            run_dashboard_local()
        elif choice == "5":
            open_azure_dashboard()
        elif choice in ("q", "quit", "exit"):
            print("\nGoodbye.\n")
            break
        else:
            print("\n  Invalid choice. Enter 1–5 or q.\n")


if __name__ == "__main__":
    main()
