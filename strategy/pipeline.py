from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fx_oanda.data.preprocess import align_price_data, build_return_matrix
from fx_oanda.filters.hmm_regime import RegimeHMM
from fx_oanda.filters.macro_guard import detect_macro_event
from fx_oanda.filters.ortho import cross_pair_correlation_filter, session_demean
from fx_oanda.models.har_rv import run_har_rv
from fx_oanda.signals.hawkes_spread import compute_hawkes_intensity, hawkes_decaying
from fx_oanda.signals.kalman_loadings import run_kalman
from fx_oanda.signals.ou_zscore import adf_pvalue, compute_zscore
from fx_oanda.signals.pca_factor import rolling_pca_factor


@dataclass
class StrategyState:
    returns: pd.DataFrame
    spreads: pd.DataFrame
    prices: dict[str, pd.DataFrame]
    factor: pd.Series
    residuals: pd.DataFrame
    zscores: pd.DataFrame
    kappas: pd.DataFrame
    ou_sigmas: pd.DataFrame       # OU sigma per pair, used for calibrated SL/TP sizing
    intensities: pd.DataFrame
    hawkes_decay: pd.DataFrame
    suppressed: pd.DataFrame
    macro_event: pd.Series
    hmm_features: pd.DataFrame
    regime: pd.Series
    har_forecasts: pd.DataFrame
    kalman_uncertainty: pd.Series
    diagnostics: dict
    train_end_time: pd.Timestamp  # last timestamp of the model-training window


def build_strategy_state(all_data: dict[str, pd.DataFrame], cfg: dict) -> StrategyState:
    returns, spreads = build_return_matrix(all_data, cfg)
    prices = align_price_data(all_data, returns.index)

    # --- Rolling / online signals: no lookahead bias ---
    factor, _, _ = rolling_pca_factor(returns, cfg["signals"]["pca_window"])
    residuals, _, kalman_uncertainty = run_kalman(returns, factor)

    # Aggregate return residuals over `signal_bars` to measure the last N-bar
    # idiosyncratic drift — captures 2-hour moves at M30, giving proper SL/TP scale.
    signal_bars = int(cfg["signals"].get("signal_bars", 4))
    residuals_signal = residuals.rolling(signal_bars, min_periods=1).sum()

    zscores, kappas, ou_sigmas = compute_zscore(residuals_signal, cfg["signals"]["ou_window"], refit_every=cfg["signals"].get("ou_refit_every", 10))
    zscores = session_demean(zscores)
    intensities = compute_hawkes_intensity(
        spreads,
        window=cfg["signals"]["hawkes_window"],
        spike_pct=cfg["signals"]["spread_percentile"],
        refit_every=cfg["signals"].get("hawkes_refit_every", 10),
    )
    hawkes_decay = hawkes_decaying(intensities)
    corr_threshold = float(cfg["signals"].get("corr_threshold", 0.6))
    suppressed = cross_pair_correlation_filter(zscores, residuals, corr_threshold=corr_threshold)
    macro_event = detect_macro_event(spreads, cfg["execution"]["macro_pairs_threshold"])

    # --- Models trained only on the train portion (no lookahead) ---
    train_fraction = float(cfg.get("train_fraction", 0.65))
    n_train = max(int(len(returns) * train_fraction), 1)
    train_end_time = returns.index[n_train - 1]

    # HAR-RV: OLS fit on train period only (forecasts applied to all bars via run_har_rv)
    har_forecasts, _ = run_har_rv(returns, cfg)

    # HMM: fit on train portion of features, predict on full series
    hmm = RegimeHMM(n_states=cfg["hmm"]["n_states"])
    hmm_features = hmm.build_features(residuals_signal, spreads, kappas, lookback=cfg["hmm"].get("corr_lookback", 20))
    hmm_train_features = hmm_features[hmm_features.index <= train_end_time]
    hmm.train(hmm_train_features)
    regime = hmm.predict_series(hmm_features)

    diagnostics = {
        "adf_pvalues": {column: adf_pvalue(residuals[column]) for column in residuals.columns},
        "hmm_state_counts": regime.value_counts().to_dict(),
        "train_end_time": str(train_end_time),
        "train_bars": n_train,
        "test_bars": len(returns) - n_train,
    }
    return StrategyState(
        returns=returns,
        spreads=spreads,
        prices=prices,
        factor=factor,
        residuals=residuals,
        zscores=zscores,
        kappas=kappas,
        ou_sigmas=ou_sigmas,
        intensities=intensities,
        hawkes_decay=hawkes_decay,
        suppressed=suppressed,
        macro_event=macro_event,
        hmm_features=hmm_features,
        regime=regime,
        har_forecasts=har_forecasts,
        kalman_uncertainty=kalman_uncertainty,
        diagnostics=diagnostics,
        train_end_time=train_end_time,
    )


def build_candidate_signals(state: StrategyState, cfg: dict, max_lookback: int | None = None) -> pd.DataFrame:
    rows = []
    pair_index = {pair: idx for idx, pair in enumerate(cfg["instruments"])}
    session_start = int(cfg["signals"].get("session_start_utc", 0))
    session_end   = int(cfg["signals"].get("session_end_utc",  24))
    kappa_min     = float(cfg["signals"].get("kappa_min", 0.0))
    index = state.returns.index[-max_lookback:] if max_lookback is not None else state.returns.index
    for timestamp in index:
        # Session filter: only trade within the configured UTC hour window.
        hour = timestamp.hour
        if not (session_start <= hour < session_end):
            continue
        if bool(state.macro_event.get(timestamp, False)):
            continue
        # HMM regime is kept as metadata but NOT used as a hard filter — it's
        # brittle out-of-sample.
        regime = str(state.regime.get(timestamp, "transitional"))
        cross_corr = float(state.hmm_features["cross_corr"].get(timestamp, 0.0))
        uncertainty = float(state.kalman_uncertainty.get(timestamp, 0.0))
        for pair in cfg["instruments"]:
            if pair not in state.zscores.columns or pair not in state.prices:
                continue
            z = float(state.zscores[pair].get(timestamp, float("nan")))
            if pd.isna(z):
                continue
            if bool(state.suppressed[pair].get(timestamp, False)):
                continue
            if not bool(state.hawkes_decay[pair].get(timestamp, False)):
                continue
            if abs(z) < float(cfg["signals"]["z_entry_weak"]):
                continue
            # Kappa filter: only trade fast-reverting pairs (high kappa → quick mean reversion).
            kappa = float(state.kappas[pair].get(timestamp, 0.0))
            if kappa < kappa_min:
                continue
            spread = float(state.spreads[pair].get(timestamp, float("nan")))
            median_spread = float(state.spreads[pair].rolling(100).median().get(timestamp, float("nan")))
            if pd.isna(spread) or pd.isna(median_spread) or spread > median_spread * float(cfg["execution"]["spread_entry_max_multiplier"]):
                continue
            price = float(state.prices[pair].loc[timestamp, "close"])
            # Use OU sigma (calibrated on the multi-bar residual signal) for SL/TP.
            # sigma is in the same units as the residual (log-return), so price * sigma
            # converts to actual price distance.  This gives properly scaled distances
            # at M30 resolution (~15-30 pips for EUR_USD).
            ou_sigma = float(state.ou_sigmas[pair].get(timestamp, 0.0))
            if ou_sigma <= 1e-8:
                continue
            z_stop = float(cfg["signals"]["z_stop"])
            z_tp = float(cfg["signals"]["z_tp"])
            stop_distance = max((z_stop - abs(z)) * ou_sigma * price, spread * 3.0, 1e-5)
            take_distance = max((abs(z) - z_tp) * ou_sigma * price, spread * 1.5, 1e-5)
            direction = -1 if z > 0 else 1
            rows.append(
                {
                    "time": timestamp,
                    "pair": pair,
                    "direction": direction,
                    "z_score": z,
                    "abs_z": abs(z),
                    "spread": spread,
                    "hawkes_intensity": float(state.intensities[pair].get(timestamp, 0.0)),
                    "kappa": kappa,
                    "har_rv": float(state.har_forecasts[pair].get(timestamp, 0.0)),
                    "cross_corr": cross_corr,
                    "kalman_uncertainty": uncertainty,
                    "regime": regime,
                    "entry_price": price,
                    "sl_price": price - direction * stop_distance,
                    "tp_price": price + direction * take_distance,
                    "pair_index": pair_index[pair],
                }
            )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows).set_index("time").sort_index()
    return frame


