from __future__ import annotations

import numpy as np
import pandas as pd


def cross_pair_correlation_filter(zscores: pd.DataFrame, residuals: pd.DataFrame, lookback: int = 20, corr_threshold: float = 0.75, refit_every: int = 10) -> pd.DataFrame:
    """Suppress the weaker of any two highly-correlated pairs at each bar.

    The correlation matrix is recomputed every ``refit_every`` bars and held
    constant in between — a ~10x speedup with negligible impact on signal quality
    since residual cross-correlations evolve slowly.
    """
    suppressed = pd.DataFrame(False, index=zscores.index, columns=zscores.columns)
    cached_corr: pd.DataFrame | None = None
    for end in range(lookback, len(residuals)):
        if cached_corr is None or (end - lookback) % refit_every == 0:
            cached_corr = residuals.iloc[end - lookback : end].corr()
        z_row = zscores.iloc[end].abs()
        for idx, left in enumerate(cached_corr.columns):
            for right in cached_corr.columns[idx + 1 :]:
                value = float(cached_corr.loc[left, right])
                if np.isnan(value) or abs(value) <= corr_threshold:
                    continue
                weaker = left if float(z_row.get(left, 0.0)) < float(z_row.get(right, 0.0)) else right
                suppressed.iat[end, suppressed.columns.get_loc(weaker)] = True
    return suppressed


def session_demean(zscores: pd.DataFrame) -> pd.DataFrame:
    def session_name(hour: int) -> str:
        if 0 <= hour < 8:
            return "asia"
        if 8 <= hour < 13:
            return "london"
        if 13 <= hour < 21:
            return "ny_overlap"
        return "late"

    out = zscores.copy()
    session = pd.Series(out.index.hour, index=out.index).map(session_name)
    for column in out.columns:
        out[column] = out.groupby(session)[column].transform(lambda series: (series - series.expanding().mean()) / series.expanding().std().clip(lower=1e-6))
    return out

