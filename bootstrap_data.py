"""
bootstrap_data.py — One-time historical data seeder for FX1.

Downloads 5+ years of M30 OHLCV from Twelve Data (free tier) and saves
as parquet files in data/cache/, matching the exact schema that fetch_oanda.py
produces. Run this ONCE before starting the live server; the live system will
then append fresh OANDA bars on each bar cycle.

Usage:
    python bootstrap_data.py --api-key YOUR_TWELVE_DATA_KEY [--years 5] [--config path/to/config.yaml]

Free API key: https://twelvedata.com/register  (no credit card required)
Free tier: 800 API credits/day, 8 req/min — enough to bootstrap all 7 pairs in ~7 minutes.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import requests

from fx_oanda.config.loader import ensure_dirs, load_config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Pair name mapping: OANDA → Twelve Data
# ---------------------------------------------------------------------------
OANDA_TO_TD = {
    "EUR_USD": "EUR/USD",
    "GBP_USD": "GBP/USD",
    "AUD_USD": "AUD/USD",
    "NZD_USD": "NZD/USD",
    "USD_CAD": "USD/CAD",
    "USD_CHF": "USD/CHF",
    "USD_JPY": "USD/JPY",
}

# Typical OANDA practice mid-spread per pair (used to synthesise bid/ask on
# historical bars where we only have mid-price from Twelve Data).
# The live OANDA bars will have real bid/ask from the cutover point onward.
TYPICAL_SPREAD = {
    "EUR_USD": 0.00010,
    "GBP_USD": 0.00015,
    "AUD_USD": 0.00015,
    "NZD_USD": 0.00020,
    "USD_CAD": 0.00020,
    "USD_CHF": 0.00015,
    "USD_JPY": 0.015,
}

TD_BASE = "https://api.twelvedata.com"
PAGE_SIZE = 5000          # max bars per request on free tier
MIN_BETWEEN_REQUESTS = 8  # seconds — free tier: 8 req/min


# ---------------------------------------------------------------------------
# Twelve Data helpers
# ---------------------------------------------------------------------------

def _td_fetch_page(
    symbol: str,
    api_key: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Fetch one page (≤5000 bars) from Twelve Data."""
    params = {
        "symbol":     symbol,
        "interval":   "30min",
        "start_date": start_date,
        "end_date":   end_date,
        "outputsize": PAGE_SIZE,
        "order":      "ASC",
        "apikey":     api_key,
        "format":     "JSON",
    }
    for attempt in range(5):
        try:
            r = requests.get(f"{TD_BASE}/time_series", params=params, timeout=30)
            r.raise_for_status()
            body = r.json()
            if body.get("status") == "error":
                code = body.get("code", 0)
                msg  = body.get("message", "")
                if code == 429 or "too many" in msg.lower():
                    wait = 15 * (2 ** attempt)
                    log.warning("Rate limited — waiting %ds", wait)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Twelve Data error {code}: {msg}")
            return body.get("values", [])
        except requests.RequestException as exc:
            wait = 5 * (2 ** attempt)
            log.warning("Request failed (%s) — retrying in %ds", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {symbol} after 5 attempts")


def fetch_td_pair(
    oanda_pair: str,
    api_key: str,
    years: int = 5,
) -> pd.DataFrame:
    """
    Fetch M30 OHLCV for one FX pair from Twelve Data, paginating backwards
    until we have `years` worth of data. Returns a DataFrame matching the
    exact schema produced by fetch_oanda.py.
    """
    td_symbol = OANDA_TO_TD[oanda_pair]
    spread_val = TYPICAL_SPREAD[oanda_pair]

    end_dt   = pd.Timestamp.utcnow().floor("30min")
    start_dt = end_dt - pd.DateOffset(years=years)

    end_str   = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")

    log.info("Fetching %s (%s) from %s to %s …", oanda_pair, td_symbol, start_str, end_str)

    all_rows: list[dict] = []
    # Paginate forward in PAGE_SIZE chunks
    cursor_start = start_dt
    while cursor_start < end_dt:
        cursor_end = min(cursor_start + pd.Timedelta(hours=PAGE_SIZE * 0.5), end_dt)
        page = _td_fetch_page(
            td_symbol,
            api_key,
            cursor_start.strftime("%Y-%m-%d %H:%M:%S"),
            cursor_end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        if page:
            all_rows.extend(page)
            log.info("  %s: got %d bars up to %s (total so far: %d)",
                     oanda_pair, len(page), page[-1]["datetime"], len(all_rows))
        else:
            log.debug("  Empty page for %s [%s → %s]", oanda_pair, cursor_start, cursor_end)

        # Advance cursor to just after the last bar received (or skip window)
        if page:
            last_ts = pd.Timestamp(page[-1]["datetime"], tz="UTC")
            cursor_start = last_ts + pd.Timedelta(minutes=30)
        else:
            cursor_start = cursor_end + pd.Timedelta(minutes=30)

        # Respect free-tier rate limit
        time.sleep(MIN_BETWEEN_REQUESTS)

    if not all_rows:
        log.error("No data received for %s!", oanda_pair)
        return pd.DataFrame()

    # ── Convert to OANDA-compatible schema ──────────────────────────────────
    rows_out = []
    for row in all_rows:
        try:
            ts    = pd.Timestamp(row["datetime"], tz="UTC")
            close = float(row["close"])
            half  = spread_val / 2.0
            rows_out.append({
                "time":      ts,
                "open":      float(row["open"]),
                "high":      float(row["high"]),
                "low":       float(row["low"]),
                "close":     close,
                "bid_close": close - half,
                "ask_close": close + half,
                "spread":    spread_val,
                "volume":    int(float(row.get("volume", 0))),
            })
        except (KeyError, ValueError, TypeError) as exc:
            log.debug("Skipping malformed row %s: %s", row, exc)

    if not rows_out:
        return pd.DataFrame()

    df = (
        pd.DataFrame(rows_out)
        .set_index("time")
        .sort_index()
    )
    # Drop duplicates (can occur at page boundaries)
    df = df[~df.index.duplicated(keep="last")]
    # Drop weekend / zero-volume bars that Twelve Data sometimes includes
    df = df[df["spread"] > 0]
    log.info("%s: %d bars retained (%s → %s)",
             oanda_pair, len(df), df.index[0], df.index[-1])
    return df


# ---------------------------------------------------------------------------
# Merge with existing OANDA cache
# ---------------------------------------------------------------------------

def merge_with_cache(historical: pd.DataFrame, cache_path: Path) -> pd.DataFrame:
    """
    If a parquet cache already exists (short OANDA history), prepend the
    historical bars so we have a seamless 5-year series.
    The OANDA bars (with real bid/ask spreads) take precedence for the
    overlapping period.
    """
    if not cache_path.exists():
        return historical

    oanda_df = pd.read_parquet(cache_path)
    if oanda_df.empty:
        return historical

    # Keep historical bars only where OANDA cache doesn't already have data
    cutoff = oanda_df.index.min()
    historical_old = historical[historical.index < cutoff]

    merged = pd.concat([historical_old, oanda_df]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    log.info("  Merged: %d historical + %d OANDA = %d total bars",
             len(historical_old), len(oanda_df), len(merged))
    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap FX1 historical data cache from Twelve Data")
    parser.add_argument("--api-key",  required=True, help="Twelve Data API key (free at twelvedata.com)")
    parser.add_argument("--years",    type=int, default=5, help="Years of history to fetch (default: 5)")
    parser.add_argument("--config",   default="", help="Path to config.yaml (default: auto-detect)")
    parser.add_argument("--pairs",    nargs="*", help="Specific pairs to fetch (default: all 7)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ensure_dirs(cfg)
    cache_dir = Path(cfg["data"]["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)

    pairs = args.pairs or cfg["instruments"]
    invalid = [p for p in pairs if p not in OANDA_TO_TD]
    if invalid:
        parser.error(f"Unknown pairs: {invalid}. Valid: {list(OANDA_TO_TD)}")

    log.info("Bootstrapping %d pairs with %d years of M30 history", len(pairs), args.years)
    log.info("Estimated time: ~%d minutes (free-tier rate limit)", len(pairs) * args.years * 2)

    success = []
    failed  = []
    for pair in pairs:
        try:
            df = fetch_td_pair(pair, args.api_key, years=args.years)
            if df.empty:
                log.error("Empty result for %s — skipping", pair)
                failed.append(pair)
                continue

            cache_path = cache_dir / f"{pair}.parquet"
            df = merge_with_cache(df, cache_path)
            df.to_parquet(cache_path)
            log.info("Saved %s: %d bars → %s", pair, len(df), cache_path)
            success.append(pair)
        except Exception as exc:
            log.error("Failed to fetch %s: %s", pair, exc)
            failed.append(pair)

    print("\n" + "=" * 50)
    print(f"Bootstrap complete: {len(success)}/{len(pairs)} pairs")
    for p in success:
        path = cache_dir / f"{p}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            print(f"  {p}: {len(df):,} bars  ({df.index[0].date()} → {df.index[-1].date()})")
    if failed:
        print(f"\nFailed pairs: {failed}")
        print("Re-run with --pairs " + " ".join(failed) + " to retry.")
    print("=" * 50)
    print("\nNext step: restart the fx1 service to pick up the new data.")
    print("  sudo systemctl restart fx1")


if __name__ == "__main__":
    main()
