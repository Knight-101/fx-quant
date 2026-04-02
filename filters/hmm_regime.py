from __future__ import annotations

import io
from contextlib import redirect_stderr

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM


def _mean_offdiag_corr(sample: pd.DataFrame) -> float:
    corr = sample.corr().to_numpy(dtype=float)
    if corr.size == 0:
        return 0.0
    mask = ~np.eye(corr.shape[0], dtype=bool)
    values = corr[mask]
    values = values[~np.isnan(values)]
    return float(values.mean()) if len(values) else 0.0


class RegimeHMM:
    def __init__(self, n_states: int = 3) -> None:
        self.n_states = n_states
        self.model = GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=200, random_state=42, min_covar=1e-4)
        self.trained = False
        self.state_map: dict[int, str] = {}

    def build_features(self, residuals: pd.DataFrame, spreads: pd.DataFrame, kappas: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
        cross_corr = pd.Series(index=residuals.index, dtype=float)
        for end in range(lookback, len(residuals)):
            cross_corr.iloc[end] = _mean_offdiag_corr(residuals.iloc[end - lookback : end])
        features = pd.DataFrame(
            {
                "cross_corr": cross_corr,
                "avg_spread": spreads.mean(axis=1),
                "avg_kappa": kappas.mean(axis=1),
                "dispersion": residuals.std(axis=1),
            }
        ).dropna()
        return features

    def train(self, features: pd.DataFrame) -> None:
        if len(features) < 100:
            self.trained = False
            return
        try:
            with redirect_stderr(io.StringIO()):
                self.model.fit(features.values)
            self.trained = True
        except Exception:
            self.trained = False
            return
        states = self.model.predict(features.values)
        mean_dispersion = {state: float(features.loc[states == state, "dispersion"].mean()) for state in range(self.n_states)}
        ordering = sorted(mean_dispersion, key=mean_dispersion.get, reverse=True)
        self.state_map = {ordering[0]: "idiosyncratic", ordering[1]: "transitional", ordering[2]: "macro"}

    def predict_series(self, features: pd.DataFrame) -> pd.Series:
        if not self.trained or features.empty:
            return pd.Series("transitional", index=features.index, dtype="object")
        states = self.model.predict(features.values)
        return pd.Series([self.state_map.get(int(state), "transitional") for state in states], index=features.index)

    def predict_regime(self, feature_row: pd.DataFrame) -> str:
        if not self.trained or feature_row.empty:
            return "transitional"
        state = int(self.model.predict(feature_row.values)[0])
        return self.state_map.get(state, "transitional")

