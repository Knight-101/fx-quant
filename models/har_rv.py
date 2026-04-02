from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant


def compute_realized_vol(returns: pd.Series) -> pd.Series:
    return returns.pow(2).rolling(1).sum().pow(0.5)


@dataclass
class HARRV:
    lags: tuple[int, ...] = (1, 8, 48)
    params: dict[str, float] | None = None

    def fit(self, rv_series: pd.Series, fit_window: int = 480) -> "HARRV":
        rv = rv_series.dropna().astype(float)
        if len(rv) < max(self.lags) + 30:
            self.params = {"const": float(rv.mean()) if len(rv) else 1e-6}
            return self
        rv = rv.iloc[-fit_window:]
        frame = pd.DataFrame(index=rv.index)
        for lag in self.lags:
            frame[f"rv_{lag}"] = rv.rolling(lag).mean()
        frame = frame.dropna()
        y = rv.reindex(frame.index)
        result = OLS(y.values, add_constant(frame.values)).fit()
        names = ["const"] + [f"rv_{lag}" for lag in self.lags]
        self.params = {name: float(value) for name, value in zip(names, result.params)}
        return self

    def forecast(self, rv_series: pd.Series) -> float:
        if not self.params:
            return float(rv_series.dropna().iloc[-1]) if len(rv_series.dropna()) else 1e-6
        forecast = self.params.get("const", 0.0)
        for lag in self.lags:
            forecast += self.params.get(f"rv_{lag}", 0.0) * float(rv_series.rolling(lag).mean().iloc[-1])
        return float(max(forecast, 1e-8))


def run_har_rv(returns: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict[str, HARRV]]:
    lags = tuple(cfg["har_rv"]["lags"])
    fit_window = int(cfg["har_rv"].get("fit_window", 480))
    # Train OLS coefficients only on the train portion to avoid lookahead bias.
    train_fraction = float(cfg.get("train_fraction", 0.65))
    n_train = max(int(len(returns) * train_fraction), max(lags) + 30)
    forecasts = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    models: dict[str, HARRV] = {}
    for column in returns.columns:
        rv = compute_realized_vol(returns[column])
        model = HARRV(lags=lags).fit(rv.iloc[:n_train], fit_window=fit_window)
        models[column] = model
        # Vectorised forecast — compute all rolling means once (O(N)) instead of
        # recomputing them inside a Python loop at each bar (was O(N²), ~440s on 65k bars).
        col_forecast = pd.Series(float(model.params.get("const", 1e-6)), index=rv.index, dtype=float)
        for lag in lags:
            coef = float(model.params.get(f"rv_{lag}", 0.0))
            if coef != 0.0:
                col_forecast = col_forecast + coef * rv.rolling(lag).mean()
        forecasts[column] = col_forecast.clip(lower=1e-8)
    return forecasts.ffill().fillna(0.0), models
