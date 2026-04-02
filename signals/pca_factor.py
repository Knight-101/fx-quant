from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


def rolling_pca_factor(returns: pd.DataFrame, window: int = 60) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    factor = pd.Series(index=returns.index, dtype=float)
    loadings = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    residuals = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)

    for end in range(window, len(returns)):
        window_slice = returns.iloc[end - window : end]
        if window_slice.isna().any().any():
            continue
        pca = PCA(n_components=1)
        pca.fit(window_slice.values)
        lam = pca.components_[0]
        r_t = returns.iloc[end].values.reshape(1, -1)
        f_t = float(pca.transform(r_t)[0, 0])
        explained = f_t * lam

        factor.iloc[end] = f_t
        loadings.iloc[end] = lam
        residuals.iloc[end] = returns.iloc[end].values - explained

    return factor, loadings, residuals

