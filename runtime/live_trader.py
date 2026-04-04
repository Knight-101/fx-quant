from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from fx_oanda.config.loader import ensure_dirs, load_config
from fx_oanda.data.fetch_oanda import append_new_bars
from fx_oanda.execution.almgren_chriss import fx_urgency_score
from fx_oanda.execution.oanda_exec import OANDAExecutor
from fx_oanda.models.kelly_sizer import compute_position_size, vol_adjusted_leverage
from fx_oanda.strategy.pipeline import build_candidate_signals, build_strategy_state

log = logging.getLogger(__name__)

# Rebuild full strategy state every N bars (each bar = 30 min).
STATE_TTL_BARS = 2
BAR_MINUTES    = 30


@dataclass
class LiveSnapshot:
    timestamp: str
    regime: str
    open_trades: list
    recent_signals: list
    diagnostics: dict


class FX1LiveTrader:
    def __init__(self, cfg_path: str | None = None) -> None:
        self.cfg = load_config(cfg_path)
        ensure_dirs(self.cfg)
        self.executor = OANDAExecutor(self.cfg)

        self.kill_switch = False

        # Load existing trade log from disk so history survives restarts
        trade_path = Path(self.cfg["paths"]["trade_log"])
        try:
            self.trade_log: list[dict] = json.loads(trade_path.read_text(encoding="utf-8")) if trade_path.exists() else []
        except Exception:
            self.trade_log = []

        # State cache: rebuilt every STATE_TTL_BARS bars
        self._cached_state = None
        self._state_expires_at: pd.Timestamp = pd.Timestamp("1970-01-01", tz="UTC")
        self._cached_data = None

        # open_trade_ids[trade_id] = {pair, fill_price, units, direction}
        # Populated on market order fill; polled each bar for close events.
        self._open_trade_ids: dict[str, dict] = {}

    # ── State caching ──────────────────────────────────────────────────────────

    def _refresh_state(self, force: bool = False) -> None:
        now = pd.Timestamp.utcnow()
        if force or self._cached_state is None or now >= self._state_expires_at:
            log.info("Rebuilding strategy state…")
            self._cached_data = append_new_bars(self.cfg)
            self._cached_state = build_strategy_state(self._cached_data, self.cfg)
            ttl = pd.Timedelta(minutes=STATE_TTL_BARS * BAR_MINUTES)
            self._state_expires_at = now + ttl
            log.info("State ready. Next rebuild at %s UTC", self._state_expires_at.strftime("%H:%M"))

    # ── Closed trade polling ───────────────────────────────────────────────────

    def _check_closed_trades(self) -> None:
        """Poll OANDA for each tracked open trade. Log realized PnL when closed by SL/TP."""
        now = pd.Timestamp.utcnow()
        for trade_id in list(self._open_trade_ids.keys()):
            meta = self._open_trade_ids[trade_id]
            try:
                trade = self.executor.get_trade(trade_id)
            except Exception as exc:
                log.warning("Could not fetch trade %s: %s", trade_id, exc)
                continue

            if trade.get("state") == "CLOSED":
                realized_pnl = float(trade.get("realizedPL", 0))
                close_price  = float(trade.get("averageClosePrice", 0))
                close_time   = trade.get("closeTime", str(now))
                close_reason = "manual"
                sl_order = trade.get("stopLossOrder") or {}
                tp_order = trade.get("takeProfitOrder") or {}
                if tp_order.get("state") == "FILLED":
                    close_reason = "tp"
                elif sl_order.get("state") == "FILLED":
                    close_reason = "sl"
                log.info(
                    "Trade CLOSED: %s trade_id=%s pnl=%.2f reason=%s",
                    meta["pair"], trade_id, realized_pnl, close_reason,
                )
                self.trade_log.append({
                    "timestamp":    close_time,
                    "event":        "close",
                    "pair":         meta["pair"],
                    "trade_id":     trade_id,
                    "fill_price":   meta["fill_price"],
                    "close_price":  close_price,
                    "units":        meta["units"],
                    "direction":    meta["direction"],
                    "pnl":          realized_pnl,
                    "close_reason": close_reason,
                })
                del self._open_trade_ids[trade_id]

    # ── Persistence ────────────────────────────────────────────────────────────

    def _write_state(self, snapshot: LiveSnapshot) -> None:
        state_path = Path(self.cfg["paths"]["dashboard_state"])
        trade_path = Path(self.cfg["paths"]["trade_log"])
        state_path.write_text(json.dumps(asdict(snapshot), indent=2, default=str), encoding="utf-8")
        trade_path.write_text(json.dumps(self.trade_log[-200:], indent=2, default=str), encoding="utf-8")

    def _kill_switch_armed(self) -> bool:
        path = Path(self.cfg["paths"]["kill_switch"])
        if not path.exists():
            return False
        return bool(json.loads(path.read_text(encoding="utf-8")).get("armed", False))

    # ── Main bar handler ───────────────────────────────────────────────────────

    def run_bar(self) -> LiveSnapshot:
        # 1. Kill switch
        if self.kill_switch or self._kill_switch_armed():
            log.warning("Kill switch armed — flattening all positions")
            self.executor.flatten_all()
            snapshot = LiveSnapshot(
                timestamp=str(pd.Timestamp.utcnow()),
                regime="halted",
                open_trades=self.executor.get_open_trades(),
                recent_signals=[],
                diagnostics={"kill_switch": True},
            )
            self._write_state(snapshot)
            return snapshot

        # 2. Poll open trades for SL/TP close events
        self._check_closed_trades()

        # 3. Refresh strategy state if cache expired
        self._refresh_state()
        state = self._cached_state

        # 4. Generate signals — only scan last 6 bars (3h window).
        signals = build_candidate_signals(state, self.cfg, max_lookback=6)
        now_utc = pd.Timestamp.utcnow()
        max_signal_age = pd.Timedelta(hours=1)

        if not signals.empty:
            latest_time = signals.index.max()
            age = now_utc - latest_time.tz_convert("UTC") if latest_time.tzinfo else now_utc - latest_time.replace(tzinfo=None).tz_localize("UTC")
            if age > max_signal_age:
                log.info("Latest signal is %.1f h old — market likely closed or no recent signal", age.total_seconds() / 3600)
                latest_signals = pd.DataFrame()
            else:
                latest_signals = signals.loc[[latest_time]].copy()
        else:
            latest_signals = pd.DataFrame()

        # 5. Account state
        open_trades = self.executor.get_open_trades()
        open_pairs  = {t["instrument"] for t in open_trades}
        account     = self.executor.get_account_summary()
        balance     = float(account["balance"])

        # 6. Place market orders for new signals
        pair_margin = float(self.cfg["risk"].get("pair_margin_cap", 10_000.0))
        cash_buffer = float(self.cfg["risk"].get("cash_buffer", 30_000.0))
        max_open    = int(self.cfg["risk"].get("max_open_trades", 2))

        for _, signal in latest_signals.iterrows():
            pair = signal["pair"]

            if pair in open_pairs:
                continue

            if len(open_trades) >= max_open:
                log.info("Max open trades reached — skipping %s", pair)
                continue

            # Cash-buffer guard: only count actually deployed margin (no pending)
            deployed_margin = sum(float(t.get("marginUsed", 0)) for t in open_trades)
            if deployed_margin + pair_margin > balance - cash_buffer:
                log.info("Cash buffer would be breached — skipping %s", pair)
                continue

            # Position sizing
            har_rv = float(signal.get("har_rv", self.cfg["risk"].get("vol_ref", 0.015)))
            lev    = vol_adjusted_leverage(
                har_rv,
                vol_ref=float(self.cfg["risk"].get("vol_ref", 0.015)),
                max_leverage=float(self.cfg["risk"].get("max_leverage", 50.0)),
            )
            entry_price = float(signal["entry_price"])
            direction   = int(signal["direction"])

            raw_units = compute_position_size(pair_margin, lev, entry_price)
            max_units = int(self.cfg["risk"].get("max_units_per_trade", 500_000))
            units = min(raw_units, max_units) * direction
            if abs(units) < 1:
                continue

            urgency = fx_urgency_score(float(signal["z_score"]), 0.5, self.cfg)
            if urgency < 0.2:
                log.info("Low urgency (%.2f) — skipping %s", urgency, pair)
                continue

            try:
                resp     = self.executor.place_market_order(
                    instrument=pair,
                    units=units,
                    sl_price=float(signal["sl_price"]),
                    tp_price=float(signal["tp_price"]),
                )
                fill_tx  = resp.get("orderFillTransaction", {})
                trade_id = str(fill_tx.get("tradeOpened", {}).get("tradeID", ""))
                fill_price = float(fill_tx.get("price", entry_price))

                log.info(
                    "Market order filled: %s %+d units @ %.5f (z=%.2f, sl=%.5f, tp=%.5f)",
                    pair, units, fill_price,
                    float(signal["z_score"]),
                    float(signal["sl_price"]),
                    float(signal["tp_price"]),
                )

                if trade_id:
                    self._open_trade_ids[trade_id] = {
                        "pair":       pair,
                        "fill_price": fill_price,
                        "units":      int(units),
                        "direction":  direction,
                    }
                    open_pairs.add(pair)
                    open_trades.append({"instrument": pair, "marginUsed": str(pair_margin)})

                self.trade_log.append({
                    "timestamp":  str(now_utc),
                    "event":      "fill",
                    "pair":       pair,
                    "trade_id":   trade_id,
                    "fill_price": fill_price,
                    "units":      int(units),
                    **{k: signal.get(k) for k in ("direction", "z_score", "regime", "sl_price", "tp_price")},
                })
            except Exception as exc:
                log.error("Failed to place market order for %s: %s", pair, exc)

        # 7. Build and persist snapshot
        snapshot = LiveSnapshot(
            timestamp=str(pd.Timestamp.utcnow()),
            regime=str(state.regime.iloc[-1]) if not state.regime.empty else "transitional",
            open_trades=self.executor.get_open_trades(),
            recent_signals=latest_signals.reset_index().to_dict(orient="records") if not latest_signals.empty else [],
            diagnostics=state.diagnostics,
        )
        self._write_state(snapshot)
        return snapshot
