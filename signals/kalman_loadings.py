from __future__ import annotations

import numpy as np
import pandas as pd


class KalmanFactorModel:
    def __init__(self, n_pairs: int, process_noise: float = 1e-5, obs_noise: float = 1e-3) -> None:
        self.n_pairs = n_pairs
        self.q = np.full(n_pairs, process_noise, dtype=float)
        self.r = float(obs_noise)
        self.lam = np.zeros(n_pairs, dtype=float)
        self.p = np.ones(n_pairs, dtype=float)

    def update(self, r_t: np.ndarray, f_t: float) -> tuple[np.ndarray, np.ndarray, float]:
        p_pred = self.p + self.q
        if abs(f_t) < 1e-8:
            self.p = p_pred
            return self.lam.copy(), r_t.copy(), float(p_pred.mean())

        s = (f_t * f_t * p_pred) + self.r
        k = (p_pred * f_t) / np.maximum(s, 1e-10)
        innov = r_t - (f_t * self.lam)
        self.lam = self.lam + (k * innov)
        self.p = (1.0 - (k * f_t)) * p_pred
        residual = r_t - (f_t * self.lam)
        return self.lam.copy(), residual, float(self.p.mean())


def run_kalman(
    returns: pd.DataFrame,
    factor: pd.Series,
    *,
    process_noise: float = 1e-5,
    obs_noise: float = 1e-3,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    model = KalmanFactorModel(returns.shape[1], process_noise=process_noise, obs_noise=obs_noise)
    residuals = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    loadings = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    uncertainty = pd.Series(index=returns.index, dtype=float)

    for timestamp, row in returns.iterrows():
        f_t = float(factor.get(timestamp, np.nan))
        if np.isnan(f_t):
            continue
        lam, resid, unc = model.update(row.values.astype(float), f_t)
        residuals.loc[timestamp] = resid
        loadings.loc[timestamp] = lam
        uncertainty.loc[timestamp] = unc

    return residuals, loadings, uncertainty.ffill().fillna(0.0)
