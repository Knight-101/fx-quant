from __future__ import annotations

import pandas as pd


def detect_macro_event(spreads: pd.DataFrame, threshold_pairs: int = 3, spike_multiplier: float = 2.5) -> pd.Series:
    rolling_median = spreads.rolling(100).median()
    spike_flags = spreads > (rolling_median * spike_multiplier)
    return spike_flags.sum(axis=1) >= int(threshold_pairs)

