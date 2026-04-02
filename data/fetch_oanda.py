from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict

import pandas as pd
import requests

log = logging.getLogger(__name__)

from fx_oanda.config.loader import ensure_dirs, load_config


def _fetch_page(instrument: str, cfg: Dict, *, count: int, to_time: str | None = None) -> pd.DataFrame:
    url = f"{cfg['oanda']['base_url'].rstrip('/')}/v3/instruments/{instrument}/candles"
    headers = {"Authorization": f"Bearer {cfg['oanda']['api_key']}"}
    params = {
        "granularity": cfg["data"]["granularity"],
        "count": int(count),
        "price": "BA",
    }
    if to_time:
        params["to"] = to_time

    response = None
    for attempt in range(6):
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code < 500:
            break
        wait = 2 ** attempt  # 1, 2, 4, 8, 16, 32 seconds
        time.sleep(wait)
    assert response is not None
    response.raise_for_status()
    candles = response.json().get("candles", [])

    rows = []
    for candle in candles:
        if not candle.get("complete", False):
            continue
        bid = candle["bid"]
        ask = candle["ask"]
        rows.append(
            {
                "time": pd.Timestamp(candle["time"], tz="UTC"),
                "open": (float(bid["o"]) + float(ask["o"])) / 2.0,
                "high": (float(bid["h"]) + float(ask["h"])) / 2.0,
                "low": (float(bid["l"]) + float(ask["l"])) / 2.0,
                "close": (float(bid["c"]) + float(ask["c"])) / 2.0,
                "bid_close": float(bid["c"]),
                "ask_close": float(ask["c"]),
                "spread": float(ask["c"]) - float(bid["c"]),
                "volume": int(candle.get("volume", 0)),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.set_index("time").sort_index()


def fetch_candles(instrument: str, cfg: Dict, *, count: int | None = None) -> pd.DataFrame:
    remaining = int(count or cfg["data"]["bars"])
    page_size = min(2500, remaining)
    cursor = None
    pages = []
    while remaining > 0:
        page_count = min(page_size, remaining)
        page = _fetch_page(instrument, cfg, count=page_count, to_time=cursor)
        if page.empty:
            break
        pages.append(page)
        oldest = page.index.min()
        cursor = oldest.isoformat()
        remaining -= len(page)
        if len(page) < page_count:
            break
    if not pages:
        return pd.DataFrame()
    combined = pd.concat(pages).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.tail(int(count or cfg["data"]["bars"]))


def fetch_all(cfg: Dict | None = None, *, force: bool = False) -> Dict[str, pd.DataFrame]:
    cfg = cfg or load_config()
    ensure_dirs(cfg)
    all_data: Dict[str, pd.DataFrame] = {}
    for instrument in cfg["instruments"]:
        path = Path(cfg["data"]["cache_dir"]) / f"{instrument}.parquet"
        if path.exists() and not force:
            all_data[instrument] = pd.read_parquet(path)
            continue
        frame = fetch_candles(instrument, cfg)
        frame.to_parquet(path)
        all_data[instrument] = frame
    return all_data


def load_cache(cfg: Dict | None = None) -> Dict[str, pd.DataFrame]:
    cfg = cfg or load_config()
    data = {}
    for instrument in cfg["instruments"]:
        path = Path(cfg["data"]["cache_dir"]) / f"{instrument}.parquet"
        data[instrument] = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    return data


def append_new_bars(cfg: Dict | None = None) -> Dict[str, pd.DataFrame]:
    """
    Append only the bars that are newer than the last cached bar.
    Preserves the full historical cache (e.g. bootstrap data) and only fetches
    the delta from OANDA. Safe to call every bar cycle.
    """
    cfg = cfg or load_config()
    ensure_dirs(cfg)
    all_data: Dict[str, pd.DataFrame] = {}

    for instrument in cfg["instruments"]:
        path = Path(cfg["data"]["cache_dir"]) / f"{instrument}.parquet"

        if not path.exists():
            # No cache at all — do a full fetch
            log.info("%s: no cache, doing full fetch", instrument)
            frame = fetch_candles(instrument, cfg)
            frame.to_parquet(path)
            all_data[instrument] = frame
            continue

        existing = pd.read_parquet(path)
        if existing.empty:
            frame = fetch_candles(instrument, cfg)
            frame.to_parquet(path)
            all_data[instrument] = frame
            continue

        # Estimate how many new bars exist since last cached bar
        last_ts = existing.index.max()
        elapsed_seconds = (pd.Timestamp.now(tz="UTC") - last_ts).total_seconds()
        bars_needed = max(int(elapsed_seconds / 1800) + 5, 10)  # +5 buffer, min 10

        new_df = fetch_candles(instrument, cfg, count=min(bars_needed, 300))
        if not new_df.empty:
            # Keep only bars strictly newer than our last cached bar
            new_df = new_df[new_df.index > last_ts]

        if not new_df.empty:
            frame = pd.concat([existing, new_df]).sort_index()
            frame = frame[~frame.index.duplicated(keep="last")]
            log.info("%s: appended %d new bars (total %d)", instrument, len(new_df), len(frame))
        else:
            frame = existing
            log.info("%s: cache up to date (%d bars)", instrument, len(frame))

        frame.to_parquet(path)
        all_data[instrument] = frame

    return all_data
