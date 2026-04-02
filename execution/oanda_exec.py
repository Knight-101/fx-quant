from __future__ import annotations

import json
from typing import Any, Dict, List

import pandas as pd
import requests


class OANDAExecutor:
    def __init__(self, cfg: Dict) -> None:
        self.cfg = cfg
        self.base = cfg["oanda"]["base_url"].rstrip("/")
        self.account = cfg["oanda"]["account_id"]
        self.headers = {
            "Authorization": f"Bearer {cfg['oanda']['api_key']}",
            "Content-Type": "application/json",
        }

    def _price_digits(self, instrument: str) -> int:
        return 3 if instrument.endswith("JPY") else 5

    def _rfctime(self, ts: pd.Timestamp) -> str:
        """Format a UTC timestamp as OANDA RFC3339."""
        return ts.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    # ── Market order ───────────────────────────────────────────────────────────
    def place_market_order(
        self,
        instrument: str,
        units: int,
        sl_price: float,
        tp_price: float,
    ) -> Dict[str, Any]:
        digits = self._price_digits(instrument)
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(units)),
                "stopLossOnFill": {"price": f"{sl_price:.{digits}f}"},
                "takeProfitOnFill": {"price": f"{tp_price:.{digits}f}"},
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        r = requests.post(
            f"{self.base}/v3/accounts/{self.account}/orders",
            headers=self.headers,
            data=json.dumps(payload),
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    # ── Limit order ────────────────────────────────────────────────────────────
    def place_limit_order(
        self,
        instrument: str,
        units: int,
        limit_price: float,
        sl_price: float,
        tp_price: float,
        expires_at: pd.Timestamp,
    ) -> str:
        """Place a GTD limit order. Returns the OANDA order ID."""
        digits = self._price_digits(instrument)
        payload = {
            "order": {
                "type": "LIMIT",
                "instrument": instrument,
                "units": str(int(units)),
                "price": f"{limit_price:.{digits}f}",
                "stopLossOnFill": {"price": f"{sl_price:.{digits}f}"},
                "takeProfitOnFill": {"price": f"{tp_price:.{digits}f}"},
                "timeInForce": "GTD",
                "gtdTime": self._rfctime(expires_at),
                "positionFill": "DEFAULT",
            }
        }
        r = requests.post(
            f"{self.base}/v3/accounts/{self.account}/orders",
            headers=self.headers,
            data=json.dumps(payload),
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        # OANDA returns orderCreateTransaction with id
        return str(body.get("orderCreateTransaction", {}).get("id", ""))

    # ── Order management ───────────────────────────────────────────────────────
    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Return order dict. Key field: order['state'] = PENDING|FILLED|CANCELLED|EXPIRED."""
        r = requests.get(
            f"{self.base}/v3/accounts/{self.account}/orders/{order_id}",
            headers=self.headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("order", {})

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        r = requests.put(
            f"{self.base}/v3/accounts/{self.account}/orders/{order_id}/cancel",
            headers=self.headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def get_open_orders(self) -> List[Dict[str, Any]]:
        r = requests.get(
            f"{self.base}/v3/accounts/{self.account}/orders?state=PENDING",
            headers=self.headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("orders", [])

    # ── Trade management ───────────────────────────────────────────────────────
    def close_trade(self, trade_id: str) -> Dict[str, Any]:
        r = requests.put(
            f"{self.base}/v3/accounts/{self.account}/trades/{trade_id}/close",
            headers=self.headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def get_open_trades(self) -> List[Dict[str, Any]]:
        r = requests.get(
            f"{self.base}/v3/accounts/{self.account}/openTrades",
            headers=self.headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("trades", [])

    def get_trade(self, trade_id: str) -> Dict[str, Any]:
        """Return a single trade dict. state = OPEN | CLOSED | CLOSE_WHEN_TRADEABLE."""
        r = requests.get(
            f"{self.base}/v3/accounts/{self.account}/trades/{trade_id}",
            headers=self.headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("trade", {})

    def get_account_summary(self) -> Dict[str, Any]:
        r = requests.get(
            f"{self.base}/v3/accounts/{self.account}/summary",
            headers=self.headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["account"]

    def flatten_all(self) -> None:
        """Close all open trades and cancel all pending orders."""
        for order in self.get_open_orders():
            try:
                self.cancel_order(order["id"])
            except Exception:
                pass
        for trade in self.get_open_trades():
            try:
                self.close_trade(trade["id"])
            except Exception:
                pass
