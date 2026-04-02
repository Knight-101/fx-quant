"""
FX1 Dashboard Backend — FastAPI + WebSocket
Runs FX1LiveTrader on M30 schedule, broadcasts live snapshots.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import statistics
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fx_oanda.config.loader import load_config
from fx_oanda.runtime.live_trader import FX1LiveTrader

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

# ---------------------------------------------------------------------------
# Config + paths
# ---------------------------------------------------------------------------
cfg = load_config()

STATE_PATH   = Path(cfg["paths"]["dashboard_state"])
TRADES_PATH  = Path(cfg["paths"]["trade_log"])
KILL_PATH    = Path(cfg["paths"]["kill_switch"])

OANDA_BASE    = cfg["oanda"]["base_url"].rstrip("/")
OANDA_ACCOUNT = cfg["oanda"]["account_id"]
OANDA_TOKEN   = cfg["oanda"]["api_key"]
OANDA_HEADERS = {
    "Authorization": f"Bearer {OANDA_TOKEN}",
    "Content-Type":  "application/json",
}

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

# ---------------------------------------------------------------------------
# Shared mutable state (all access from async event loop)
# ---------------------------------------------------------------------------
_trader:          FX1LiveTrader | None = None
_trader_running:  bool = False
_connected_ws:    set[WebSocket] = set()


# ---------------------------------------------------------------------------
# OANDA helpers (blocking — call in executor)
# ---------------------------------------------------------------------------

def _oanda_account_summary() -> dict[str, Any]:
    if not OANDA_ACCOUNT or not OANDA_TOKEN:
        return {"balance": 0, "nav": 0, "unrealized_pnl": 0, "currency": "SGD", "open_trade_count": 0}
    try:
        r = requests.get(
            f"{OANDA_BASE}/v3/accounts/{OANDA_ACCOUNT}/summary",
            headers=OANDA_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        acct = r.json()["account"]
        return {
            "balance":          float(acct.get("balance", 0)),
            "nav":              float(acct.get("NAV", acct.get("balance", 0))),
            "unrealized_pnl":   float(acct.get("unrealizedPL", 0)),
            "currency":         acct.get("currency", "SGD"),
            "open_trade_count": int(acct.get("openTradeCount", 0)),
        }
    except Exception as exc:
        log.warning("OANDA account fetch failed: %s", exc)
        return {"balance": 0, "nav": 0, "unrealized_pnl": 0, "currency": "SGD", "open_trade_count": 0}


# ---------------------------------------------------------------------------
# Metrics computation from trade_log
# ---------------------------------------------------------------------------

def _parse_ts(s: str) -> datetime:
    """Parse OANDA timestamp strings — handles tz-aware/naive, nano/micro/ms precision."""
    s = s.strip().replace(' ', 'T')
    s = re.sub(r'Z$', '+00:00', s)
    s = re.sub(r'(\.\d{6})\d+', r'\1', s)   # truncate sub-microsecond digits
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.fromisoformat(re.sub(r'[+-]\d{2}:\d{2}$', '', s))


def _oanda_open_trades() -> list[dict]:
    if not OANDA_ACCOUNT or not OANDA_TOKEN:
        return []
    try:
        r = requests.get(
            f"{OANDA_BASE}/v3/accounts/{OANDA_ACCOUNT}/openTrades",
            headers=OANDA_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("trades", [])
    except Exception as exc:
        log.warning("OANDA open trades fetch failed: %s", exc)
        return []


def _compute_metrics(trade_log: list[dict], initial_capital: float = 500_000.0) -> dict[str, Any]:
    # Only "close" events carry realized PnL from OANDA.
    closes = [e for e in trade_log if e.get("event") == "close" and e.get("pnl") is not None]
    total_trades = len(closes)
    pnls: list[float] = [float(e["pnl"]) for e in closes]

    net_pnl      = sum(pnls) if pnls else 0.0
    winners      = [p for p in pnls if p > 0]
    losers       = [p for p in pnls if p < 0]
    win_rate     = len(winners) / total_trades if total_trades else 0.0
    avg_win      = sum(winners) / len(winners) if winners else 0.0
    avg_loss     = sum(losers)  / len(losers)  if losers  else 0.0
    gross_profit = sum(winners) if winners else 0.0
    gross_loss   = abs(sum(losers)) if losers else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    expectancy   = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    # Max drawdown — relative to initial_capital so % stays within [-100%, 0%]
    max_drawdown = 0.0
    if pnls:
        peak = running = initial_capital
        for p in pnls:
            running += p
            peak     = max(peak, running)
            max_drawdown = min(max_drawdown, (running - peak) / peak)

    # Sharpe — annualised from actual trade frequency
    sharpe = 0.0
    if len(pnls) >= 4:
        try:
            times = sorted(
                _parse_ts(e["timestamp"]).replace(tzinfo=None)
                for e in closes if "timestamp" in e
            )
            if len(times) >= 2:
                span_days = max((times[-1] - times[0]).total_seconds() / 86400, 1e-6)
                trades_per_year = total_trades / (span_days / 365.25)
            else:
                trades_per_year = 52.0
            mu  = statistics.mean(pnls)
            std = statistics.stdev(pnls)
            if std > 0:
                sharpe = round((mu / std) * math.sqrt(trades_per_year), 2)
        except Exception:
            pass

    return {
        "total_trades":  total_trades,
        "win_rate":      round(win_rate, 4),
        "net_pnl":       round(net_pnl, 2),
        "avg_win":       round(avg_win, 2),
        "avg_loss":      round(avg_loss, 2),
        "expectancy":    round(expectancy, 2),
        "sharpe":        round(sharpe, 2),
        "max_drawdown":  round(max_drawdown, 4),
        "profit_factor": round(profit_factor, 4),
    }


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

async def _build_snapshot(loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
    # Read JSON artifacts (async IO)
    live_state: dict[str, Any] = {}
    trade_log:  list[dict]     = []

    if STATE_PATH.exists():
        async with aiofiles.open(STATE_PATH, encoding="utf-8") as f:
            raw = await f.read()
        try:
            live_state = json.loads(raw)
        except json.JSONDecodeError:
            pass

    if TRADES_PATH.exists():
        async with aiofiles.open(TRADES_PATH, encoding="utf-8") as f:
            raw = await f.read()
        try:
            trade_log = json.loads(raw)
        except json.JSONDecodeError:
            pass

    # OANDA live calls (blocking — run in executor)
    account, open_trades = await asyncio.gather(
        loop.run_in_executor(None, _oanda_account_summary),
        loop.run_in_executor(None, _oanda_open_trades),
    )

    kill_switch = False
    if KILL_PATH.exists():
        try:
            kill_switch = json.loads(KILL_PATH.read_text(encoding="utf-8")).get("armed", False)
        except Exception:
            pass

    # Derive initial capital: current balance minus all realized PnL
    closes = [e for e in trade_log if e.get("event") == "close" and e.get("pnl") is not None]
    net_pnl_so_far = sum(float(e["pnl"]) for e in closes)
    initial_capital = max(float(account.get("balance", 500_000)) - net_pnl_so_far, 100_000.0)
    metrics = _compute_metrics(trade_log, initial_capital=initial_capital)

    return {
        "type":           "snapshot",
        "ts":             datetime.now(timezone.utc).isoformat(),
        "trader_running": _trader_running,
        "kill_switch":    kill_switch,
        "account":        account,
        "regime":         live_state.get("regime", "unknown"),
        "open_trades":    open_trades,
        "recent_signals": live_state.get("recent_signals", []),
        "diagnostics":    live_state.get("diagnostics", {}),
        "trade_log":      trade_log[-200:],
        "metrics":        metrics,
    }


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _ws_broadcaster(loop: asyncio.AbstractEventLoop) -> None:
    """Broadcast full snapshot to all WebSocket clients every 10 s."""
    while True:
        await asyncio.sleep(10)
        if not _connected_ws:
            continue
        try:
            snap = await _build_snapshot(loop)
            msg  = json.dumps(snap, default=str)
        except Exception as exc:
            log.warning("Snapshot build error: %s", exc)
            continue

        dead: set[WebSocket] = set()
        for ws in list(_connected_ws):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        _connected_ws.difference_update(dead)


def _next_bar_delay_seconds() -> float:
    """Seconds until next M30 bar close + 60s buffer."""
    now = datetime.now(timezone.utc)
    # M30 bars close at :00 and :30 — next close
    minute    = now.minute
    second    = now.second
    past_half = minute % 30 * 60 + second  # seconds past the last bar close
    bar_secs  = 30 * 60
    wait      = bar_secs - past_half + 60   # buffer
    if wait < 30:
        wait += bar_secs
    return float(wait)


async def _trading_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _trader_running
    log.info("Trading loop started. Waiting for first M30 bar…")
    while _trader_running:
        delay = _next_bar_delay_seconds()
        log.info("Next bar in %.0f s (%.1f min)", delay, delay / 60)
        await asyncio.sleep(delay)
        if not _trader_running:
            break
        if _trader is None:
            continue
        log.info("Running bar…")
        try:
            await loop.run_in_executor(None, _trader.run_bar)
        except Exception as exc:
            log.error("run_bar error: %s", exc)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _trader, _trader_running
    loop = asyncio.get_event_loop()

    _trader         = FX1LiveTrader()
    _trader_running = True

    trader_task     = asyncio.create_task(_trading_loop(loop))
    broadcast_task  = asyncio.create_task(_ws_broadcaster(loop))

    log.info("FX1 backend started. Trader running: %s", _trader_running)
    yield

    # Shutdown
    _trader_running = False
    trader_task.cancel()
    broadcast_task.cancel()
    try:
        await asyncio.gather(trader_task, broadcast_task, return_exceptions=True)
    except Exception:
        pass
    log.info("FX1 backend shutdown.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="FX1 Dashboard API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def get_status():
    loop = asyncio.get_event_loop()
    snap = await _build_snapshot(loop)
    return JSONResponse(snap)


@app.get("/api/account")
async def get_account():
    loop = asyncio.get_event_loop()
    acct = await loop.run_in_executor(None, _oanda_account_summary)
    return JSONResponse(acct)


@app.post("/api/kill")
async def kill_switch():
    KILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    KILL_PATH.write_text(json.dumps({"armed": True}), encoding="utf-8")
    log.warning("Kill switch armed via API")
    return {"status": "armed"}


@app.post("/api/disarm")
async def disarm_kill_switch():
    if KILL_PATH.exists():
        KILL_PATH.unlink()
    log.info("Kill switch disarmed via API")
    return {"status": "disarmed"}


@app.post("/api/trader/start")
async def start_trader():
    global _trader_running
    loop = asyncio.get_event_loop()
    if _trader_running:
        return {"status": "already_running"}
    _trader_running = True
    asyncio.create_task(_trading_loop(loop))
    log.info("Trader started via API")
    return {"status": "started"}


@app.post("/api/trader/stop")
async def stop_trader():
    global _trader_running
    _trader_running = False
    log.info("Trader stopped via API")
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _connected_ws.add(ws)
    log.info("WebSocket client connected (%d total)", len(_connected_ws))
    loop = asyncio.get_event_loop()

    # Send immediate snapshot on connect
    try:
        snap = await _build_snapshot(loop)
        await ws.send_text(json.dumps(snap, default=str))
    except Exception as exc:
        log.warning("Initial snapshot send failed: %s", exc)

    try:
        while True:
            # Keep-alive: wait for ping or disconnect
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _connected_ws.discard(ws)
        log.info("WebSocket client disconnected (%d remaining)", len(_connected_ws))


# ---------------------------------------------------------------------------
# Serve React frontend (SPA fallback)
# ---------------------------------------------------------------------------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Don't intercept API/WS routes
        if full_path.startswith("api/") or full_path == "ws":
            return JSONResponse({"error": "not found"}, status_code=404)
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"error": "Frontend not built. Run: cd frontend && npm run build"}, status_code=503)
