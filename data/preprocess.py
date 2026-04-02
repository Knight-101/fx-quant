from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd


def build_return_matrix(all_data: Dict[str, pd.DataFrame], cfg: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    signs = cfg["usd_base_sign"]
    returns = {}
    spreads = {}

    for instrument, frame in all_data.items():
        if frame.empty:
            continue
        returns[instrument] = frame["close"].pct_change() * float(signs.get(instrument, 1.0))
        spreads[instrument] = frame["spread"]

    return_frame = pd.DataFrame(returns).dropna().sort_index()
    spread_frame = pd.DataFrame(spreads).reindex(return_frame.index).sort_index()
    return return_frame, spread_frame


def align_price_data(all_data: Dict[str, pd.DataFrame], index: pd.Index) -> Dict[str, pd.DataFrame]:
    aligned = {}
    for instrument, frame in all_data.items():
        if frame.empty:
            aligned[instrument] = frame
            continue
        aligned[instrument] = frame.reindex(index).ffill().dropna()
    return aligned

