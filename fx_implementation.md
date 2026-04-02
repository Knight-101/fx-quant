# FX1 — USD Factor Residual + Hawkes Spread Timing
### Full Implementation Guide | OANDA FX Majors | M30 Execution

---

## Table of Contents
1. [Strategy Overview](#strategy-overview)
2. [Project Structure](#project-structure)
3. [Data Pipeline](#data-pipeline)
4. [Signal Construction](#signal-construction)
5. [Orthogonalization](#orthogonalization)
7. [Regime Filter — HMM](#regime-filter--hmm)
8. [Volatility Forecast](#volatility-forecast)
9. [Execution Model](#execution-model)
10. [Order Placement & Risk](#order-placement--risk)
11. [Backtester](#backtester)
12. [Live Runtime — OANDA](#live-runtime--oanda)
13. [Dash UI](#dash-ui)
14. [Full Stack Summary](#full-stack-summary)
15. [Deployment Path](#deployment-path)

---

## Strategy Overview

```
Core idea: Extract the latent USD common factor across 7 majors via PCA.
Each pair carries a residual component orthogonal to pure USD movement.
When a pair's residual dislocates beyond its statistical bounds,
it mean-reverts predictably. Hawkes process on spread dynamics
provides precise entry timing within the dislocation window.

No LOB required. No tick data required.
Everything computable from OANDA candles + spread alone.
```

**Instruments:** EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF, USDJPY

**Timeframe:** M30

**Frequency:** 5–15 trades/day across all 7 pairs

**Execution:** OANDA practice account via REST API

---

## Project Structure

```
fx_oanda/
│
├── config/
│   └── config.yaml               # All params in one place
│
├── data/
│   ├── fetch_oanda.py             # OANDA candle + spread fetcher
│   ├── preprocess.py              # Return construction, alignment
│   └── cache/                     # Parquet cache of fetched bars
│
├── signals/
│   ├── pca_factor.py              # PCA USD factor extraction
│   ├── kalman_loadings.py         # Dynamic Kalman filter loadings
│   ├── ou_zscore.py               # OU calibration + Z-score signal
│   └── hawkes_spread.py           # Hawkes intensity on spread
│
├── filters/
│   ├── hmm_regime.py              # 3-state HMM regime filter
│   ├── ortho.py                   # Cross-pair orthogonalization
│   └── macro_guard.py             # Event + simultaneous spike filter
│
├── models/
│   ├── har_rv.py                  # HAR-RV volatility forecast
│   └── kelly_sizer.py             # Fractional Kelly position sizing
│
├── execution/
│   ├── almgren_chriss.py          # A-C adapted for FX spread cost
│   └── oanda_exec.py              # OANDA order placement + management
│
├── backtest/
│   ├── engine.py                  # Event-driven backtester
│   ├── metrics.py                 # Sharpe, drawdown, win rate, etc.
│   └── results/                   # Trade logs, equity curves
│
├── runtime/
│   └── live_trader.py             # Live paper trading loop
│
├── dashboard/
│   └── app.py                     # Dash UI + kill switch
│
├── notebooks/
│   └── FX1_deliverable.ipynb      # Project notebook
│
└── docs/
    └── FX1_strategy.md            # This file
```

---

## Config

```yaml
# config/config.yaml

oanda:
  account_id: "YOUR_ACCOUNT_ID"
  api_key: "YOUR_API_KEY"
  environment: "practice"           # practice | live
  base_url: "https://api-fxpractice.oanda.com"

instruments:
  - "EUR_USD"
  - "GBP_USD"
  - "AUD_USD"
  - "NZD_USD"
  - "USD_CAD"
  - "USD_CHF"
  - "USD_JPY"

# USD-base sign correction
usd_base_sign:
  EUR_USD: 1
  GBP_USD: 1
  AUD_USD: 1
  NZD_USD: 1
  USD_CAD: -1
  USD_CHF: -1
  USD_JPY: -1

data:
  granularity: "M30"
  bars: 5000
  cache_dir: "data/cache"

signals:
  pca_window: 60                    # bars for rolling PCA
  ou_window: 720                    # bars for OU calibration (15 days at M30)
  z_entry_strong: 2.5
  z_entry_weak: 2.0
  z_stop: 3.5
  z_tp: 0.5
  hawkes_window: 100                # bars for Hawkes baseline
  spread_percentile: 90             # spread spike threshold

hmm:
  n_states: 3
  retrain_hours: 24
  features: ["cross_corr", "avg_spread", "ou_kappa", "residual_dispersion"]

har_rv:
  lags: [1, 8, 48]                  # M30: 1bar, 4hr, 1day

kelly:
  fraction: 0.25                    # quarter Kelly
  max_risk_per_trade: 0.02          # 2% account

execution:
  entry_timeout_bars: 2
  time_stop_bars: 8                 # 4 hours at M30
  macro_pairs_threshold: 3          # simultaneous spike guard
  spread_entry_max_multiplier: 1.5  # skip if spread > 1.5x median

risk:
  daily_drawdown_kill: 0.03         # 3% daily drawdown → halt
  max_open_trades: 4
  max_trades_per_pair: 1
```

---

## Data Pipeline

### fetch_oanda.py

```python
import requests
import pandas as pd
import os
import yaml

def load_config():
    with open("config/config.yaml") as f:
        return yaml.safe_load(f)

def fetch_candles(instrument, cfg):
    url = f"{cfg['oanda']['base_url']}/v3/instruments/{instrument}/candles"
    headers = {"Authorization": f"Bearer {cfg['oanda']['api_key']}"}
    params = {
        "granularity": cfg["data"]["granularity"],
        "count": cfg["data"]["bars"],
        "price": "BA"                 # bid + ask for spread
    }
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    candles = r.json()["candles"]

    rows = []
    for c in candles:
        if not c["complete"]:
            continue
        mid_o = (float(c["bid"]["o"]) + float(c["ask"]["o"])) / 2
        mid_c = (float(c["bid"]["c"]) + float(c["ask"]["c"])) / 2
        spread = float(c["ask"]["c"]) - float(c["bid"]["c"])
        rows.append({
            "time": pd.Timestamp(c["time"]),
            "open": mid_o,
            "close": mid_c,
            "volume": int(c["volume"]),
            "spread": spread
        })

    df = pd.DataFrame(rows).set_index("time")
    return df

def fetch_all(cfg):
    os.makedirs(cfg["data"]["cache_dir"], exist_ok=True)
    all_data = {}
    for inst in cfg["instruments"]:
        path = f"{cfg['data']['cache_dir']}/{inst}.parquet"
        df = fetch_candles(inst, cfg)
        df.to_parquet(path)
        all_data[inst] = df
        print(f"Fetched {len(df)} bars for {inst}")
    return all_data

def load_cache(cfg):
    all_data = {}
    for inst in cfg["instruments"]:
        path = f"{cfg['data']['cache_dir']}/{inst}.parquet"
        all_data[inst] = pd.read_parquet(path)
    return all_data
```

### preprocess.py

```python
import pandas as pd
import numpy as np

def build_return_matrix(all_data, cfg):
    """
    Align all pairs on common index.
    Sign-adjust so all returns move with USD weakness.
    """
    signs = cfg["usd_base_sign"]
    returns = {}
    spreads = {}

    for inst, df in all_data.items():
        ret = df["close"].pct_change()
        sign = signs[inst]
        returns[inst] = ret * sign          # USD-normalized direction
        spreads[inst] = df["spread"]

    R = pd.DataFrame(returns).dropna()
    S = pd.DataFrame(spreads).reindex(R.index)
    return R, S
```

---

## Signal Construction

### pca_factor.py

```python
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

def rolling_pca_factor(R, window=60):
    """
    Rolling PCA on return matrix.
    Returns PC1 (USD factor) and residuals per pair.
    """
    factor = pd.Series(index=R.index, dtype=float)
    loadings = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)
    residuals = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)

    for i in range(window, len(R)):
        window_data = R.iloc[i-window:i].values
        pca = PCA(n_components=1)
        pca.fit(window_data)

        # PC1 score for current bar
        f_t = pca.transform(R.iloc[[i]].values)[0, 0]
        lam = pca.components_[0]             # loadings vector

        factor.iloc[i] = f_t
        loadings.iloc[i] = lam

        # Residual = actual return - factor-explained return
        explained = f_t * lam
        residuals.iloc[i] = R.iloc[i].values - explained

    return factor, loadings, residuals
```

### kalman_loadings.py

```python
import numpy as np
import pandas as pd

class KalmanFactorModel:
    """
    Kalman filter for dynamic factor loadings.
    State: loading vector Λ_t per pair
    Observation: r_t = F_t * Λ_t + ε_t
    """

    def __init__(self, n_pairs, process_noise=1e-5, obs_noise=1e-3):
        self.n = n_pairs
        self.Q = process_noise * np.eye(n_pairs)   # state noise
        self.R = obs_noise                          # observation noise
        self.lam = np.zeros(n_pairs)               # initial loadings
        self.P = np.eye(n_pairs)                   # initial covariance

    def update(self, r_t, f_t):
        """
        r_t: return vector (n_pairs,)
        f_t: scalar USD factor score
        Returns updated loadings and residual vector
        """
        # Predict
        P_pred = self.P + self.Q

        # Innovation per pair
        r_hat = f_t * self.lam
        innov = r_t - r_hat

        # Kalman gain
        S = f_t**2 * P_pred + self.R * np.eye(self.n)
        K = P_pred * f_t / (f_t**2 * np.trace(P_pred) + self.R * self.n)

        # Update
        self.lam = self.lam + K.diagonal() * innov
        self.P = (np.eye(self.n) - np.outer(K.diagonal(), f_t * np.ones(self.n))) @ P_pred

        residual = r_t - f_t * self.lam
        return self.lam.copy(), residual

def run_kalman(R, factor, process_noise=1e-5, obs_noise=1e-3):
    n_pairs = R.shape[1]
    km = KalmanFactorModel(n_pairs, process_noise, obs_noise)
    residuals = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)
    loadings_hist = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)

    for i, (idx, row) in enumerate(R.iterrows()):
        f_t = factor.loc[idx] if idx in factor.index else 0.0
        if np.isnan(f_t):
            continue
        lam, resid = km.update(row.values, f_t)
        residuals.loc[idx] = resid
        loadings_hist.loc[idx] = lam

    return residuals, loadings_hist
```

### ou_zscore.py

```python
import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

def calibrate_ou(resid_series, window=720):
    """
    Fit OU process to residual series via OLS on AR(1).
    Returns kappa (mean reversion speed), mu, sigma.
    """
    e = resid_series.dropna().values[-window:]
    if len(e) < 50:
        return None, None, None

    y = e[1:]
    x = add_constant(e[:-1])
    res = OLS(y, x).fit()

    a, b = res.params[0], res.params[1]
    # OU parameters from AR(1) discretization
    # b = exp(-kappa * dt), dt = 1 bar
    kappa = -np.log(max(b, 1e-6))
    mu = a / (1 - b)
    sigma = np.std(res.resid)

    return kappa, mu, sigma

def compute_zscore(residuals, window=720):
    """
    Rolling OU calibration + Z-score per pair.
    """
    zscores = pd.DataFrame(index=residuals.index, columns=residuals.columns, dtype=float)
    kappas = pd.DataFrame(index=residuals.index, columns=residuals.columns, dtype=float)

    for col in residuals.columns:
        for i in range(window, len(residuals)):
            sub = residuals[col].iloc[i-window:i]
            kappa, mu, sigma = calibrate_ou(sub)
            if sigma is None or sigma == 0:
                continue
            z = (residuals[col].iloc[i] - mu) / sigma
            zscores.at[residuals.index[i], col] = z
            kappas.at[residuals.index[i], col] = kappa

    return zscores, kappas
```

### hawkes_spread.py

```python
import numpy as np
import pandas as pd
from scipy.optimize import minimize

def fit_hawkes(event_times, T, mu0=0.1, alpha0=0.5, beta0=1.0):
    """
    MLE fit of Hawkes process parameters.
    event_times: array of event timestamps (in bar units)
    T: total observation window length
    """
    def neg_log_likelihood(params):
        mu, alpha, beta = params
        if mu <= 0 or alpha <= 0 or beta <= 0 or alpha >= beta:
            return 1e10
        n = len(event_times)
        ll = -mu * T
        R = 0.0
        for i in range(n):
            if i > 0:
                R = R * np.exp(-beta * (event_times[i] - event_times[i-1])) + 1
            intensity = mu + alpha * R
            ll += np.log(max(intensity, 1e-10))
            ll -= alpha / beta * (1 - np.exp(-beta * (T - event_times[i])))
        return -ll

    res = minimize(neg_log_likelihood, [mu0, alpha0, beta0],
                   method="Nelder-Mead",
                   options={"maxiter": 1000, "xatol": 1e-6})
    return res.x  # mu, alpha, beta

def compute_hawkes_intensity(spreads, window=100, spike_pct=90):
    """
    Rolling Hawkes intensity on spread spike events.
    Returns intensity series per pair.
    """
    intensities = pd.DataFrame(index=spreads.index, columns=spreads.columns, dtype=float)

    for col in spreads.columns:
        s = spreads[col].values
        for i in range(window, len(s)):
            sub = s[i-window:i]
            threshold = np.percentile(sub, spike_pct)
            event_idx = np.where(sub > threshold)[0].astype(float)

            if len(event_idx) < 5:
                intensities.at[spreads.index[i], col] = 0.0
                continue

            try:
                mu, alpha, beta = fit_hawkes(event_idx, float(window))
                # Current intensity
                lam = mu
                for t_i in event_idx:
                    lam += alpha * np.exp(-beta * (window - t_i))
                intensities.at[spreads.index[i], col] = lam
            except Exception:
                intensities.at[spreads.index[i], col] = 0.0

    return intensities

def hawkes_decaying(intensities, lookback=3):
    """
    Returns True per cell if intensity is declining over last N bars.
    Declining intensity = liquidity returning = good entry timing.
    """
    return intensities.diff(lookback) < 0
```

---

## Orthogonalization

### ortho.py

```python
import numpy as np
import pandas as pd

def cross_pair_correlation_filter(zscores, residuals, lookback=20, corr_threshold=0.6):
    """
    If two pairs have highly correlated residuals → suppress lower |Z| one.
    Prevents doubling up on same implicit bet.
    """
    suppressed = pd.DataFrame(False, index=zscores.index, columns=zscores.columns)

    for i in range(lookback, len(residuals)):
        sub = residuals.iloc[i-lookback:i]
        corr_matrix = sub.corr()
        z_row = zscores.iloc[i].abs()

        for p1 in corr_matrix.columns:
            for p2 in corr_matrix.columns:
                if p1 >= p2:
                    continue
                if abs(corr_matrix.loc[p1, p2]) > corr_threshold:
                    # Suppress the weaker signal
                    weaker = p1 if z_row[p1] < z_row[p2] else p2
                    suppressed.at[residuals.index[i], weaker] = True

    return suppressed

def remove_carry_contamination(residuals, swap_rates):
    """
    Residualize residuals against interest rate differential (carry).
    swap_rates: DataFrame of OANDA swap rates per pair, aligned to residuals index.
    """
    clean_residuals = residuals.copy()
    for col in residuals.columns:
        if col not in swap_rates.columns:
            continue
        from statsmodels.regression.linear_model import OLS
        from statsmodels.tools import add_constant
        y = residuals[col].dropna().values
        x = swap_rates[col].reindex(residuals[col].dropna().index).fillna(0).values
        if len(y) < 50:
            continue
        res = OLS(y, add_constant(x)).fit()
        clean_residuals.loc[residuals[col].dropna().index, col] = res.resid
    return clean_residuals

def session_demean(zscores):
    """
    Demean Z-scores within trading session.
    Sessions: Asia (0-8 UTC), London (8-16 UTC), NY (13-21 UTC)
    """
    def get_session(hour):
        if 0 <= hour < 8:
            return "asia"
        elif 8 <= hour < 13:
            return "london"
        elif 13 <= hour < 21:
            return "ny_overlap"
        else:
            return "late"

    zscores = zscores.copy()
    zscores["session"] = zscores.index.hour.map(get_session)
    for col in zscores.columns[:-1]:
        zscores[col] = zscores.groupby("session")[col].transform(
            lambda x: (x - x.expanding().mean()) / x.expanding().std().clip(lower=1e-6)
        )
    return zscores.drop(columns="session")
```

### macro_guard.py

```python
import pandas as pd
import numpy as np

def detect_macro_event(spreads, threshold_pairs=3, spike_multiplier=2.5):
    """
    If N+ pairs show simultaneous spread spike → macro event.
    Returns boolean series: True = macro event detected at this bar.
    """
    rolling_med = spreads.rolling(100).median()
    spike_flags = spreads > (rolling_med * spike_multiplier)
    macro_event = spike_flags.sum(axis=1) >= threshold_pairs
    return macro_event
```

---

## Regime Filter — HMM

### hmm_regime.py

```python
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

class RegimeHMM:
    def __init__(self, n_states=3):
        self.n_states = n_states
        self.model = GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=200,
            random_state=42
        )
        self.trained = False
        self.state_map = {}      # maps HMM state idx to regime label

    def build_features(self, residuals, spreads, kappas):
        """
        HMM observation features:
        1. Cross-pair return correlation (mean of off-diagonal)
        2. Average spread level (normalized)
        3. Mean OU kappa (mean reversion speed)
        4. Residual dispersion (std across pairs per bar)
        """
        corr_series = residuals.rolling(20).corr().groupby(level=0).apply(
            lambda x: (x.values.sum() - len(x)) / (len(x) * (len(x) - 1))
            if len(x) > 1 else 0
        )
        avg_spread = spreads.mean(axis=1)
        avg_kappa = kappas.mean(axis=1)
        dispersion = residuals.std(axis=1)

        features = pd.DataFrame({
            "cross_corr": corr_series,
            "avg_spread": avg_spread,
            "avg_kappa": avg_kappa,
            "dispersion": dispersion
        }).dropna()

        return features

    def train(self, features):
        X = features.values
        self.model.fit(X)
        self.trained = True
        states = self.model.predict(X)
        # Label states by dispersion (high dispersion = idiosyncratic = best)
        mean_disp = {s: features["dispersion"].values[states == s].mean()
                     for s in range(self.n_states)}
        sorted_states = sorted(mean_disp, key=mean_disp.get, reverse=True)
        self.state_map = {
            sorted_states[0]: "idiosyncratic",
            sorted_states[1]: "transitional",
            sorted_states[2]: "macro"
        }
        print(f"HMM trained. State map: {self.state_map}")

    def predict_regime(self, features_row):
        if not self.trained:
            return "transitional"
        X = features_row.values.reshape(1, -1)
        state = self.model.predict(X)[0]
        return self.state_map.get(state, "transitional")
```

---

## Volatility Forecast

### har_rv.py

```python
import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

def compute_realized_vol(returns, window=1):
    return (returns ** 2).rolling(window).sum() ** 0.5

class HARRV:
    """
    HAR-RV model: RV_t = b0 + b1*RV_1bar + b2*RV_8bar + b3*RV_48bar
    At M30: 1bar=30min, 8bars=4hr, 48bars=1day
    """
    def __init__(self, lags=(1, 8, 48)):
        self.lags = lags
        self.params = {}

    def fit(self, rv_series):
        rv = rv_series.dropna()
        X_dict = {"const": np.ones(len(rv))}
        for lag in self.lags:
            X_dict[f"rv_{lag}"] = rv.rolling(lag).mean().values
        X = pd.DataFrame(X_dict).dropna()
        y = rv.iloc[len(rv) - len(X):].values
        res = OLS(y, X.values).fit()
        self.params = dict(zip(X.columns, res.params))
        return self

    def forecast(self, rv_series):
        rv_vals = {f"rv_{lag}": rv_series.rolling(lag).mean().iloc[-1]
                   for lag in self.lags}
        forecast = self.params.get("const", 0)
        for lag in self.lags:
            forecast += self.params.get(f"rv_{lag}", 0) * rv_vals[f"rv_{lag}"]
        return max(forecast, 1e-8)

def run_har_rv(returns, cfg):
    lags = cfg["har_rv"]["lags"]
    forecasts = {}
    models = {}
    for col in returns.columns:
        rv = compute_realized_vol(returns[col])
        har = HARRV(lags=lags).fit(rv)
        models[col] = har
        forecasts[col] = har.forecast(rv)
    return forecasts, models
```

---

## Execution Model

### kelly_sizer.py

```python
def fractional_kelly(p_win, rr_ratio, fraction=0.25, max_risk=0.02):
    """
    p_win: estimated win probability (0.5 default)
    rr_ratio: TP/SL ratio
    fraction: Kelly fraction (0.25 = quarter Kelly)
    max_risk: hard cap on account risk per trade
    """
    p_lose = 1 - p_win
    kelly_full = (p_win * rr_ratio - p_lose) / rr_ratio
    kelly_full = max(kelly_full, 0)
    kelly_frac = kelly_full * fraction
    return min(kelly_frac, max_risk)

def compute_position_size(account_balance, risk_fraction,
                          sl_pips, pip_value):
    """
    Convert risk fraction to units.
    sl_pips: stop loss distance in pips
    pip_value: value of 1 pip per unit (pair-specific)
    """
    risk_amount = account_balance * risk_fraction
    units = risk_amount / (sl_pips * pip_value)
    return int(units)
```

### almgren_chriss.py

```python
def fx_urgency_score(z_score, hawkes_decay_rate, cfg):
    """
    FX-adapted urgency. No market impact model needed at retail size.
    Urgency determines limit vs market order and timeout.
    """
    z_norm = min(abs(z_score) / cfg["signals"]["z_entry_strong"], 1.5)
    urgency = (0.5 * z_norm +
               0.5 * min(hawkes_decay_rate, 1.0))
    return urgency

def entry_order_type(urgency):
    if urgency >= 0.75:
        return "MARKET", 0
    elif urgency >= 0.55:
        return "LIMIT", 2       # 2-bar timeout
    else:
        return "SKIP", 0
```

---

## Order Placement & Risk

### oanda_exec.py

```python
import requests
import json
import pandas as pd

class OANDAExecutor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg["oanda"]["base_url"]
        self.headers = {
            "Authorization": f"Bearer {cfg['oanda']['api_key']}",
            "Content-Type": "application/json"
        }
        self.account = cfg["oanda"]["account_id"]
        self.open_trades = {}

    def place_market_order(self, instrument, units, sl_price, tp_price):
        endpoint = f"{self.base}/v3/accounts/{self.account}/orders"
        order = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "stopLossOnFill": {"price": f"{sl_price:.5f}"},
                "takeProfitOnFill": {"price": f"{tp_price:.5f}"},
                "timeInForce": "FOK"
            }
        }
        r = requests.post(endpoint, headers=self.headers, data=json.dumps(order))
        r.raise_for_status()
        return r.json()

    def close_trade(self, trade_id):
        endpoint = f"{self.base}/v3/accounts/{self.account}/trades/{trade_id}/close"
        r = requests.put(endpoint, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def get_open_trades(self):
        endpoint = f"{self.base}/v3/accounts/{self.account}/openTrades"
        r = requests.get(endpoint, headers=self.headers)
        r.raise_for_status()
        return r.json().get("trades", [])

    def get_account_summary(self):
        endpoint = f"{self.base}/v3/accounts/{self.account}/summary"
        r = requests.get(endpoint, headers=self.headers)
        r.raise_for_status()
        return r.json()["account"]

    def flatten_all(self):
        trades = self.get_open_trades()
        for t in trades:
            self.close_trade(t["id"])
        print(f"Flattened {len(trades)} trades")
```

---

## Backtester

### engine.py

```python
import pandas as pd
import numpy as np

class FX1Backtester:
    def __init__(self, cfg):
        self.cfg = cfg
        self.trades = []
        self.equity_curve = []

    def run(self, signals_df, price_data, account_balance=100_000):
        """
        signals_df columns: time, pair, direction, z_score,
                            sl_price, tp_price, units
        price_data: dict of pair -> OHLCV DataFrame
        """
        balance = account_balance
        open_positions = {}

        for idx, row in signals_df.iterrows():
            pair = row["pair"]
            prices = price_data[pair]
            if idx not in prices.index:
                continue

            entry_price = prices.loc[idx, "close"]
            direction = row["direction"]
            sl = row["sl_price"]
            tp = row["tp_price"]
            units = row["units"]
            time_stop_bars = self.cfg["execution"]["time_stop_bars"]

            # Check open position limit
            if len(open_positions) >= self.cfg["risk"]["max_open_trades"]:
                continue
            if pair in open_positions:
                continue

            # Forward simulate
            future = prices.loc[idx:].iloc[1:time_stop_bars+1]
            exit_price = None
            exit_reason = "time"
            exit_time = future.index[-1] if len(future) > 0 else idx

            for bar_idx, bar in future.iterrows():
                high, low = bar["close"], bar["close"]
                if direction == 1:
                    if bar["close"] >= tp:
                        exit_price = tp
                        exit_reason = "tp"
                        exit_time = bar_idx
                        break
                    elif bar["close"] <= sl:
                        exit_price = sl
                        exit_reason = "sl"
                        exit_time = bar_idx
                        break
                else:
                    if bar["close"] <= tp:
                        exit_price = tp
                        exit_reason = "tp"
                        exit_time = bar_idx
                        break
                    elif bar["close"] >= sl:
                        exit_price = sl
                        exit_reason = "sl"
                        exit_time = bar_idx
                        break

            if exit_price is None:
                exit_price = future.iloc[-1]["close"] if len(future) > 0 else entry_price

            pnl = (exit_price - entry_price) * direction * units
            spread_cost = prices.loc[idx, "spread"] * units
            net_pnl = pnl - spread_cost

            balance += net_pnl
            self.trades.append({
                "entry_time": idx,
                "exit_time": exit_time,
                "pair": pair,
                "direction": direction,
                "entry": entry_price,
                "exit": exit_price,
                "pnl": net_pnl,
                "reason": exit_reason,
                "balance": balance
            })
            self.equity_curve.append({"time": exit_time, "balance": balance})

        return pd.DataFrame(self.trades)

    def metrics(self, trades_df):
        if trades_df.empty:
            return {}
        wins = trades_df[trades_df["pnl"] > 0]
        losses = trades_df[trades_df["pnl"] <= 0]
        equity = pd.DataFrame(self.equity_curve).set_index("time")["balance"]
        drawdown = (equity - equity.cummax()) / equity.cummax()

        return {
            "total_trades": len(trades_df),
            "win_rate": len(wins) / len(trades_df),
            "avg_win": wins["pnl"].mean() if len(wins) > 0 else 0,
            "avg_loss": losses["pnl"].mean() if len(losses) > 0 else 0,
            "profit_factor": abs(wins["pnl"].sum() / losses["pnl"].sum())
                             if len(losses) > 0 else np.inf,
            "net_pnl": trades_df["pnl"].sum(),
            "sharpe": trades_df["pnl"].mean() / trades_df["pnl"].std()
                      * np.sqrt(252 * 16) if trades_df["pnl"].std() > 0 else 0,
            "max_drawdown": drawdown.min(),
            "total_return": (equity.iloc[-1] / equity.iloc[0] - 1)
                            if len(equity) > 1 else 0
        }
```

---

## Live Runtime — OANDA

### live_trader.py

```python
import time
import yaml
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from data.fetch_oanda import fetch_candles, load_config
from signals.pca_factor import rolling_pca_factor
from signals.kalman_loadings import run_kalman
from signals.ou_zscore import compute_zscore
from signals.hawkes_spread import compute_hawkes_intensity, hawkes_decaying
from filters.hmm_regime import RegimeHMM
from filters.macro_guard import detect_macro_event
from filters.ortho import cross_pair_correlation_filter, session_demean
from models.har_rv import run_har_rv
from models.kelly_sizer import fractional_kelly, compute_position_size
from execution.almgren_chriss import fx_urgency_score, entry_order_type
from execution.oanda_exec import OANDAExecutor

class FX1LiveTrader:
    def __init__(self, cfg_path="config/config.yaml"):
        self.cfg = load_config()
        self.executor = OANDAExecutor(self.cfg)
        self.hmm = RegimeHMM(n_states=self.cfg["hmm"]["n_states"])
        self.running = True
        self.kill_switch = False
        self.trade_log = []

    def run_bar(self):
        """
        Execute one M30 bar cycle.
        Called at top of each completed M30 bar.
        """
        if self.kill_switch:
            print("Kill switch active — halted")
            return

        # 1. Fetch latest bars
        all_data = {}
        for inst in self.cfg["instruments"]:
            all_data[inst] = fetch_candles(inst, self.cfg)

        # 2. Build return + spread matrices
        from data.preprocess import build_return_matrix
        R, S = build_return_matrix(all_data, self.cfg)

        # 3. Check daily drawdown kill
        acct = self.executor.get_account_summary()
        balance = float(acct["balance"])
        nav = float(acct["NAV"])
        daily_dd = (nav - balance) / balance
        if daily_dd < -self.cfg["risk"]["daily_drawdown_kill"]:
            print(f"Daily drawdown kill triggered: {daily_dd:.2%}")
            self.executor.flatten_all()
            self.kill_switch = True
            return

        # 4. Macro guard
        macro = detect_macro_event(S, self.cfg["execution"]["macro_pairs_threshold"])
        if macro.iloc[-1]:
            print("Macro event detected — flattening and suppressing")
            self.executor.flatten_all()
            return

        # 5. Signal pipeline
        factor, _, _ = rolling_pca_factor(R, self.cfg["signals"]["pca_window"])
        residuals, loadings = run_kalman(R, factor)
        zscores, kappas = compute_zscore(residuals, self.cfg["signals"]["ou_window"])
        intensities = compute_hawkes_intensity(S, self.cfg["signals"]["hawkes_window"],
                                               self.cfg["signals"]["spread_percentile"])
        decaying = hawkes_decaying(intensities)
        zscores = session_demean(zscores)
        suppressed = cross_pair_correlation_filter(zscores, residuals)

        # 6. Regime filter
        hmm_features = self.hmm.build_features(residuals, S, kappas)
        if len(hmm_features) > 100:
            self.hmm.train(hmm_features)
        regime = self.hmm.predict_regime(hmm_features.iloc[[-1]])
        if regime == "macro":
            print(f"HMM: macro regime — no trades")
            return

        # 7. HAR-RV
        har_forecasts, _ = run_har_rv(R, self.cfg)

        # 8. Check each pair for signals
        for inst in self.cfg["instruments"]:
            if inst not in zscores.columns:
                continue
            z = zscores[inst].iloc[-1]
            if pd.isna(z):
                continue
            if suppressed[inst].iloc[-1]:
                continue
            if not decaying[inst].iloc[-1]:
                continue

            entry_threshold = self.cfg["signals"]["z_entry_weak"]
            if abs(z) < entry_threshold:
                continue

            # Direction: negative Z = pair cheap = buy (long)
            direction = -1 if z > 0 else 1

            # Current spread check
            current_spread = S[inst].iloc[-1]
            med_spread = S[inst].rolling(100).median().iloc[-1]
            if current_spread > med_spread * self.cfg["execution"]["spread_entry_max_multiplier"]:
                continue

            # Sizing
            rv = har_forecasts.get(inst, 0.001)
            sl_dist = rv * self.cfg["signals"]["z_stop"]
            tp_dist = rv * self.cfg["signals"]["z_tp"]

            risk_frac = fractional_kelly(
                0.5,
                tp_dist / sl_dist,
                self.cfg["kelly"]["fraction"],
                self.cfg["kelly"]["max_risk_per_trade"]
            )

            price = all_data[inst]["close"].iloc[-1]
            sl_price = price - direction * sl_dist
            tp_price = price + direction * tp_dist
            units = int(balance * risk_frac / sl_dist) * direction

            if abs(units) < 1:
                continue

            # Urgency
            hawkes_decay_rate = float(intensities[inst].diff(3).iloc[-1] or 0)
            urgency = fx_urgency_score(z, hawkes_decay_rate, self.cfg)
            order_type, timeout = entry_order_type(urgency)

            if order_type == "SKIP":
                continue

            # Check open trade limits
            open_trades = self.executor.get_open_trades()
            if len(open_trades) >= self.cfg["risk"]["max_open_trades"]:
                continue
            pair_open = any(t["instrument"] == inst for t in open_trades)
            if pair_open:
                continue

            # Place order
            result = self.executor.place_market_order(inst, units, sl_price, tp_price)
            print(f"Order placed: {inst} {units} units | "
                  f"Z={z:.2f} | regime={regime}")
            self.trade_log.append({
                "time": datetime.now(timezone.utc),
                "pair": inst,
                "direction": direction,
                "units": units,
                "z": z,
                "regime": regime,
            })

    def start(self, poll_seconds=30):
        print("FX1 Live Trader started")
        while self.running:
            try:
                self.run_bar()
            except Exception as e:
                print(f"Runtime error: {e}")
            time.sleep(poll_seconds)
```

---

## Dash UI

### dashboard/app.py

```python
import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objs as go
import pandas as pd
import yaml

app = dash.Dash(__name__)
trader = None  # Injected at runtime

app.layout = html.Div([
    html.H2("FX1 — USD Factor Residual + Hawkes Spread"),

    # Kill switch
    html.Div([
        html.Button("KILL SWITCH", id="kill-btn",
                    style={"background": "red", "color": "white",
                           "fontSize": "18px", "padding": "10px 24px"}),
        html.Span(id="kill-status", style={"marginLeft": "20px"})
    ], style={"marginBottom": "20px"}),

    # Regime indicator
    html.Div([
        html.H4("Current Regime:"),
        html.Div(id="regime-display",
                 style={"fontSize": "24px", "fontWeight": "bold"})
    ]),

    # Z-scores per pair
    dcc.Graph(id="zscore-chart"),

    # Equity curve
    dcc.Graph(id="equity-chart"),

    # Open trades table
    html.H4("Open Trades"),
    html.Div(id="trades-table"),

    # Trade log
    html.H4("Recent Signals"),
    html.Div(id="signal-log"),

    dcc.Interval(id="refresh", interval=30_000, n_intervals=0)
])

@app.callback(
    Output("kill-status", "children"),
    Input("kill-btn", "n_clicks"),
    prevent_initial_call=True
)
def kill_switch(n):
    if trader:
        trader.kill_switch = True
        trader.executor.flatten_all()
    return "⛔ KILL SWITCH ACTIVATED — All positions flattened"

@app.callback(
    [Output("zscore-chart", "figure"),
     Output("equity-chart", "figure"),
     Output("regime-display", "children"),
     Output("trades-table", "children"),
     Output("signal-log", "children")],
    Input("refresh", "n_intervals")
)
def update_dashboard(_):
    # Z-score chart
    zscore_fig = go.Figure()
    if trader and hasattr(trader, "last_zscores"):
        for col in trader.last_zscores.columns:
            z_series = trader.last_zscores[col].tail(100)
            zscore_fig.add_trace(go.Scatter(
                x=z_series.index, y=z_series.values, name=col))
        zscore_fig.add_hline(y=2.0, line_dash="dash", line_color="green")
        zscore_fig.add_hline(y=-2.0, line_dash="dash", line_color="green")
        zscore_fig.add_hline(y=3.5, line_dash="dash", line_color="red")
        zscore_fig.add_hline(y=-3.5, line_dash="dash", line_color="red")
    zscore_fig.update_layout(title="Residual Z-Scores", height=350)

    # Equity curve
    equity_fig = go.Figure()
    if trader and trader.trade_log:
        log = pd.DataFrame(trader.trade_log)
        equity_fig.add_trace(go.Scatter(
            x=log["time"], y=log.index, name="Trade count"))
    equity_fig.update_layout(title="Trade Activity", height=300)

    # Regime
    regime = trader.hmm.predict_regime(
        trader.last_hmm_features.iloc[[-1]]
    ) if trader and hasattr(trader, "last_hmm_features") else "unknown"
    regime_colors = {
        "idiosyncratic": "green",
        "transitional": "orange",
        "macro": "red"
    }
    regime_display = html.Span(
        regime.upper(),
        style={"color": regime_colors.get(regime, "gray")}
    )

    # Open trades
    open_trades = trader.executor.get_open_trades() if trader else []
    trades_table = html.Table([
        html.Tr([html.Th(c) for c in ["Pair", "Units", "Open P/L"]])] +
        [html.Tr([
            html.Td(t.get("instrument", "")),
            html.Td(t.get("currentUnits", "")),
            html.Td(f"{float(t.get('unrealizedPL', 0)):.2f}")
        ]) for t in open_trades]
    )

    # Signal log
    log_items = []
    if trader:
        for entry in trader.trade_log[-10:][::-1]:
            log_items.append(html.P(
                f"{entry['time'].strftime('%H:%M')} | {entry['pair']} | "
                f"Z={entry['z']:.2f} | conf={entry['confidence']:.2f} | "
                f"regime={entry['regime']}"
            ))

    return zscore_fig, equity_fig, regime_display, trades_table, log_items

if __name__ == "__main__":
    app.run(debug=False, port=8050)
```

---

## Full Stack Summary

```
OANDA M30 candles + spread — 7 USD majors
    ↓
PCA → USD common factor extraction → pair residuals ε_t
    ↓
Kalman filter → dynamic factor loadings → adaptive residual
    ↓
OU process → Z-score dislocation signal per pair
    ↓
Hawkes spread intensity → entry timing (wait for liquidity return)
    ↓
Cross-pair orthogonalization → suppress correlated pair double-ups
    ↓
3-state HMM → idiosyncratic regime only, hard flatten on macro
    ↓
HAR-RV per pair → dynamic OU thresholds + spread-adjusted vol
    ↓
Quarter-Kelly sizing → 2% hard cap per trade
    ↓
Market/limit entry, 4hr time stop, macro spike hard exit
```

---

## Realistic Alpha Expectation

| Metric | Estimate |
|---|---|
| Signal horizon | 1–4 hours (2–8 bars at M30) |
| Trade frequency | 5–15 trades/day across all pairs |
| Win rate | 55–62% |
| R:R | 1.5:1 – 2:1 |
| Sharpe (pre-cost) | 1.5–2.5 |
| Primary cost risk | OANDA spread wider than ECN — eats thin edges |
| Key risk | Macro event during hold — HMM + macro stop manages this |

---

## Deployment Path

```
Week 1:
  → Run fetch_oanda.py → validate 5000 bars per pair
  → Build PCA + Kalman pipeline
  → Validate residuals are stationary (ADF test per pair)
  → Plot Z-scores — confirm mean reversion behavior

Week 2:
  → Calibrate OU parameters per pair
  → Build Hawkes spread intensity
  → Backtest signal alone (no HMM)
  → Measure raw signal predictive power

Week 3:
  → Add HMM regime filter → measure regime-conditional performance
  → Full strategy backtest with sizing + stops
  → Target: positive Sharpe, win rate > 50%, max DD < 15%

Week 4:
  → Deploy live_trader.py on OANDA practice account
  → Run Dash dashboard locally
  → Monitor for 5 trading days
  → Validate live signal matches backtest signal distribution
```

---

## Key Implementation Notes

```
1. ADF test on residuals before going live:
   from statsmodels.tsa.stattools import adfuller
   p_val = adfuller(residuals[pair].dropna())[1]
   Assert p_val < 0.05 — if not, OU assumption is invalid

2. Kalman process noise Q is critical:
   Too high → loadings too jumpy → noisy residuals
   Too low  → loadings too stiff → stale residuals
   Tune on validation set: target residual half-life of 5–15 bars

3. Hawkes fitting is slow offline:
   Pre-compute rolling intensities in batch, cache to parquet
   At runtime: only compute last bar update, not full refit

4. HMM state labeling is heuristic:
   Always inspect state means after training
   Verify "idiosyncratic" state matches low-correlation periods

5. OANDA spread is the biggest cost:
   EUR_USD ~0.9 pips, GBP_USD ~1.2 pips
   Only enter when expected move > 3× spread round-trip
   This filters out most M30 signals — that's correct behavior
```
