from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def fit_hawkes(event_times: np.ndarray, horizon: float, mu0: float = 0.1, alpha0: float = 0.2, beta0: float = 1.0) -> tuple[float, float, float]:
    def objective(params: np.ndarray) -> float:
        mu, alpha, beta = params
        if mu <= 0 or alpha < 0 or beta <= 0 or alpha >= beta:
            return 1e12
        log_like = -mu * horizon
        excitation = 0.0
        for idx, t_i in enumerate(event_times):
            if idx > 0:
                excitation = excitation * np.exp(-beta * (t_i - event_times[idx - 1])) + 1.0
            intensity = mu + alpha * excitation
            log_like += np.log(max(intensity, 1e-12))
            log_like -= (alpha / beta) * (1.0 - np.exp(-beta * (horizon - t_i)))
        return -log_like

    result = minimize(objective, x0=np.array([mu0, alpha0, beta0]), method="Nelder-Mead", options={"maxiter": 100, "xatol": 1e-4, "fatol": 1e-4})
    mu, alpha, beta = result.x
    return float(mu), float(alpha), float(beta)


def compute_hawkes_intensity(spreads: pd.DataFrame, window: int = 100, spike_pct: float = 90, refit_every: int = 10) -> pd.DataFrame:
    intensities = pd.DataFrame(index=spreads.index, columns=spreads.columns, dtype=float)
    params_cache = {column: (0.05, 0.10, 1.00) for column in spreads.columns}

    for column in spreads.columns:
        series = spreads[column].astype(float)
        for end in range(window, len(series)):
            sample = series.iloc[end - window : end]
            threshold = np.percentile(sample, spike_pct)
            events = np.where(sample.values > threshold)[0].astype(float)
            if len(events) < 5:
                intensities.iat[end, intensities.columns.get_loc(column)] = 0.0
                continue
            if (end - window) % max(refit_every, 1) == 0:
                try:
                    params_cache[column] = fit_hawkes(events, float(window))
                except Exception:
                    pass
            mu, alpha, beta = params_cache[column]
            intensity = mu + alpha * np.sum(np.exp(-beta * (window - events)))
            intensities.iat[end, intensities.columns.get_loc(column)] = float(intensity)

    return intensities.fillna(0.0)


def hawkes_decaying(intensities: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    # Allow entry when intensity is declining, at baseline (zero), or below its rolling mean
    # (i.e. spread-spike activity is not currently elevated relative to recent history).
    rolling_mean = intensities.rolling(100, min_periods=20).mean()
    return (intensities.diff(lookback) < 0.0) | (intensities <= rolling_mean)
