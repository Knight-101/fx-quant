from __future__ import annotations

import numpy as np
import pandas as pd

from fx_oanda.config.loader import ensure_dirs, load_config
from fx_oanda.data.preprocess import build_return_matrix
from fx_oanda.strategy.pipeline import build_candidate_signals, build_strategy_state


def _synthetic_frame(seed: int, start: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=360, freq="30min", tz="UTC")
    returns = rng.normal(0.0, 0.001, len(index))
    close = 1.0 + np.cumsum(returns)
    spread = np.abs(rng.normal(0.00008, 0.00002, len(index)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.0005,
            "low": close - 0.0005,
            "close": close,
            "bid_close": close - spread / 2.0,
            "ask_close": close + spread / 2.0,
            "spread": spread,
            "volume": rng.integers(800, 2000, len(index)),
        },
        index=index,
    )


def test_strategy_state_builds() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    all_data = {pair: _synthetic_frame(idx + 1, "2026-01-01") for idx, pair in enumerate(cfg["instruments"])}
    returns, spreads = build_return_matrix(all_data, cfg)
    assert not returns.empty
    assert not spreads.empty
    state = build_strategy_state(all_data, cfg)
    signals = build_candidate_signals(state, cfg)
    assert not state.returns.empty
    assert {"adf_pvalues", "hmm_state_counts"}.issubset(state.diagnostics.keys())
    assert isinstance(signals, pd.DataFrame)
