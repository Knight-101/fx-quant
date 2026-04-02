from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.stattools import adfuller


def calibrate_ou(residual_series: pd.Series) -> tuple[float | None, float | None, float | None]:
    clean = residual_series.dropna().astype(float)
    if len(clean) < 50:
        return None, None, None
    y = clean.iloc[1:].to_numpy()
    x = add_constant(clean.iloc[:-1].to_numpy())
    result = OLS(y, x).fit()
    a, b = float(result.params[0]), float(result.params[1])
    b = min(max(b, 1e-6), 0.999999)
    kappa = float(-np.log(b))
    mu = float(a / max(1.0 - b, 1e-8))
    sigma = float(np.std(result.resid))
    return kappa, mu, sigma


def compute_zscore(residuals: pd.DataFrame, window: int = 720, refit_every: int = 10) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute OU z-scores with sparse OLS refitting for speed.

    Returns (zscores, kappas, sigmas).  sigmas are in the same units as residuals
    and are used downstream for calibrated SL/TP distance sizing.

    OLS parameters are re-estimated every ``refit_every`` bars and held constant
    in between — ~10x faster with negligible accuracy loss.
    """
    zscores = pd.DataFrame(index=residuals.index, columns=residuals.columns, dtype=float)
    kappas  = pd.DataFrame(index=residuals.index, columns=residuals.columns, dtype=float)
    sigmas  = pd.DataFrame(index=residuals.index, columns=residuals.columns, dtype=float)

    for column in residuals.columns:
        series = residuals[column]
        cached_kappa: float | None = None
        cached_mu:    float | None = None
        cached_sigma: float | None = None
        col_idx = zscores.columns.get_loc(column)
        for end in range(window, len(series)):
            if cached_sigma is None or (end - window) % refit_every == 0:
                sample = series.iloc[end - window : end]
                k, m, s = calibrate_ou(sample)
                if s is not None and s > 1e-10:
                    cached_kappa, cached_mu, cached_sigma = k, m, s
            if cached_sigma is None or cached_sigma <= 1e-10:
                continue
            zscores.iat[end, col_idx] = (float(series.iloc[end]) - cached_mu) / cached_sigma
            kappas.iat[end,  col_idx] = cached_kappa
            sigmas.iat[end,  col_idx] = cached_sigma

    return zscores, kappas, sigmas


def adf_pvalue(series: pd.Series) -> float:
    clean = series.dropna().astype(float)
    if len(clean) < 50:
        return 1.0
    return float(adfuller(clean)[1])

