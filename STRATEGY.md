# FX1 — Mean-Reversion FX Strategy

**Live at:** `http://135.235.139.80:8000`
**Account:** OANDA Practice | SGD ~493,000 | 7 G10 pairs | M30 bars

---

## Strategy Overview

FX1 is a statistical mean-reversion strategy on G10 FX pairs. The core idea: a basket of correlated currency pairs shares a latent factor (broadly, "USD strength"). PCA extracts that factor; the residual for each pair is a near-stationary Ornstein-Uhlenbeck process. When the residual drifts far from zero, the strategy bets on reversion.

**Universe:** EUR/USD, GBP/USD, AUD/USD, NZD/USD, USD/CAD, USD/CHF, USD/JPY
**Timeframe:** M30 (30-minute bars) — ~5 years of data (~62,000 bars per pair)
**Hold time:** Until SL or TP hit (no time-stop in live — only in backtest at 6 bars = 3h)
**Session:** 00:00–12:00 UTC (Asian open + London open — deepest liquidity, best mean-reversion behaviour)

---

## Signal Pipeline

```
Raw prices (M30 OANDA)
        │
        ▼
   Session Filter
   ─ Only bars within 00:00–12:00 UTC are considered
   ─ US afternoon (12:00–22:00 UTC) excluded: USD macro flow dominates
        │
        ▼
   Macro Guard Filter
   ─ Detects simultaneous spread spikes across ≥3 pairs (2.5× rolling median)
   ─ Entire timestamp skipped — indicates a news/macro event affecting the basket
        │
        ▼
   PCA Factor Extraction (60-bar rolling)
   ─ Finds dominant co-movement direction across 7 pairs
   ─ Returns projected onto PC1 to extract "FX beta"
        │
        ▼
   Kalman Filter (dynamic loadings)
   ─ Tracks time-varying beta between each pair and the PCA factor
   ─ Produces kalman_uncertainty: confidence in current loadings (attached to signal)
        │
        ▼
   OU Residual (720-bar rolling window = 15 days)
   ─ Residual = return − β × PC1  (using Kalman beta)
   ─ Aggregated over last 4 bars (2-hour drift window) to reduce noise
   ─ Fit OU process: mean-reversion speed κ, long-run mean μ, vol σ
   ─ z-score = (residual − μ) / (σ / √(2κ))
        │
        ▼
   Session Demean
   ─ Z-scores demeaned within each session (Asia / London / NY) via expanding mean/std
   ─ Removes systematic intraday bias per session
        │
        ▼
   Z-Score Threshold
   ─ |z| > 1.5 (weak entry) or > 1.8 (strong entry)
   ─ Grid-proven: lower z degrades quality
        │
        ▼
   Hawkes Intensity Gate (100-bar window)
   ─ Fits Hawkes process on spread spike events (spread > 90th percentile of sample)
   ─ Entry ALLOWED when intensity is declining or at/below its 100-bar rolling mean
   ─ Entry BLOCKED when intensity is currently rising (spread-spike clustering in progress)
        │
        ▼
   Cross-Pair Correlation Filter (corr_threshold = 0.75)
   ─ If two pairs' residuals are correlated > 0.75 (20-bar window), suppress the weaker z-score
   ─ Prevents doubling up on the same underlying USD move
        │
        ▼
   Spread Entry Filter
   ─ Skip if current spread > 1.5× rolling median spread (100-bar median)
   ─ Prevents entering on wide/illiquid markets
        │
        ▼
   CANDIDATE SIGNAL  (pair, direction, z_score, entry_price, sl_price, tp_price, regime, kappa)
```

**HMM Regime (metadata only):** A 3-state Gaussian HMM classifies each bar into:
- `idiosyncratic` — high cross-pair dispersion; pairs moving independently (best for this strategy)
- `transitional` — moderate regime
- `macro` — low dispersion; pairs co-moving together (USD macro dominance)

The HMM state is attached to each signal as metadata and shown on the dashboard but **is NOT used as a hard entry filter** — it was found to be too brittle out-of-sample.

---

## Execution

### Entry — Market Orders
- Signal fires → market order placed immediately on bar detection
- No limit order / GTD expiry / fill-polling — executes at current mid price
- Only 1 trade per pair; skip pair if already has open trade

### SL / TP Calculation
```
direction  = -1 if z > 0 (short) else +1 (long)

stop_distance = max( (z_stop − |z|) × ou_sigma × price,  spread × 3.0 )
take_distance = max( (|z| − z_tp)  × ou_sigma × price,  spread × 1.5 )

sl_price  = entry_price − direction × stop_distance
tp_price  = entry_price + direction × take_distance
```
Where `z_stop=2.2`, `z_tp=0.5`, `ou_sigma` = OU vol estimate for that pair at signal time.

SL/TP are attached to the OANDA order on fill (`stopLossOnFill`, `takeProfitOnFill`). OANDA manages exit server-side — no dependency on local process staying alive.

| Entry z | SL distance | TP distance | TP:SL ratio |
|---------|-------------|-------------|-------------|
| 1.5 (min) | 0.70 × σ | 1.00 × σ | 1.43× |
| 1.8 | 0.40 × σ | 1.30 × σ | 3.25× |
| 2.0 | 0.20 × σ | 1.50 × σ | 7.50× |

### Position Sizing — Vol-Adjusted Leverage
```
har_rv      = HAR-RV forecast (lags: 1, 8, 48 bars; 2400-bar fit window ≈ 50 days)
leverage    = min(vol_ref / har_rv,  max_leverage)
            = min(0.030 / har_rv,    50)
units       = (pair_margin × leverage) / entry_price
```
- `pair_margin = SGD 200,000` per trade
- At median signal vol (har_rv ≈ 0.00043): leverage hits 50× cap
- High-vol pairs (har_rv ≈ 0.001): leverage ≈ 30×
- Hard caps: `max_leverage=50`, `max_units_per_trade=50M` (safety only)

### Risk Controls
| Parameter | Value | Rationale |
|---|---|---|
| Max open trades | 2 | Grid-search sweet spot |
| Pair margin cap | SGD 200,000 | 2 × 200k = 400k deployed; fits within 443k available |
| Cash buffer | SGD 50,000 | Reserve; never deployed |
| Stop-loss | z_stop = 2.2 | Beyond 2σ: mean-reversion hypothesis invalidated |
| Take-profit | z_tp = 0.5 | Mean-reversion target |
| Max trades/pair | 1 | No pyramiding |

---

## Backtest Results

### Walk-Forward (out-of-sample, last 35% of data)

| Metric | Value |
|---|---|
| Annual return | **14.4%** |
| Sharpe ratio | **1.99** |
| Max drawdown | −3.4% |
| Win rate | 56.4% |
| Profit factor | 1.74 |
| Total trades | 117 (test period) |
| Avg PnL/trade | SGD ~1,157 |
| Avg hold | ~3 hours |

*Capital: SGD 500,000. Sharpe annualized using actual trades/year. Backtest uses limit orders with assume_all_fills=true — live uses market orders, so execution costs are slightly different.*

### Benchmark Comparison (walk-forward test period: Jun 2024 – Mar 2026)

| Metric | FX1 Strategy | EUR/USD Buy-and-Hold | Risk-Free (US T-Bill) |
|---|---|---|---|
| Ann. Return | **+14.4%** | +4.2% | ~5.25% |
| Sharpe Ratio | **1.99** | 0.55 | — |
| Max Drawdown | **−3.4%** | −9.1% | — |

EUR/USD B&H: 1.0738 → 1.1558 over the same 1.78-year window. FX1 delivers **3.4× the annualised return** of EUR/USD buy-and-hold, with **3.6× higher Sharpe** and **2.7× lower drawdown**.

### 5-Fold Walk-Forward Cross-Validation

| Fold | Ann. Return | Sharpe | Win Rate | Profit Factor | Trades |
|---|---|---|---|---|---|
| 1 | 8.82% | 1.45 | 46.7% | 1.81 | 15 |
| 2 | 14.64% | 1.18 | 41.7% | 1.45 | 36 |
| 3 | 5.30% | 0.63 | 48.6% | 1.16 | 37 |
| 4 | 14.57% | 1.52 | 51.2% | 1.44 | 41 |
| 5 | 14.53% | 1.92 | 56.1% | 1.74 | 107 |
| **AVG** | **11.57%** | **1.34** | **48.9%** | **1.52** | **47.2** |

All 5 out-of-sample folds are profitable. CV graphs: `backtest/results/cross_validation/`

---

## Key Design Decisions

### Why 00:00–12:00 UTC Session Filter?
Asian open (00:00) + London open (08:00) has best signal-to-noise for mean reversion. US afternoon (12:00–22:00 UTC) shows lower win rates — USD macro flow dominates and pairs trend rather than revert.

### Why max_open=2?
- max_open=1: blocks ~44% of signals (pair occupied)
- max_open=2: captures most signals, 2 × SGD 200k = SGD 400k deployed
- max_open=3+: win rate degrades; signals become correlated (all pairs reacting to the same USD move)

### Why HAR-RV for sizing?
Captures multi-scale FX vol: intraday (lag 1 bar), daily (lag 8 bars), weekly (lag 48 bars). Low vol → larger size → higher expected PnL per trade. Inverse-vol leverage targets consistent dollar risk per trade.

### Why z_stop=2.2?
Beyond 2σ, the OU mean-reversion hypothesis is statistically invalidated — a persistent trend is more likely than a reversion. Tighter stops improve both Sharpe and profit factor in grid search.

### Hawkes Gate Logic
Counter-intuitive: the Hawkes gate ALLOWS entry when spread-spike intensity is declining or at baseline. It BLOCKS when spikes are clustering (rising intensity) — a sign of ongoing market stress or news absorption. Once the dust settles (intensity decays), the residual displacement is more likely to revert cleanly.

---

## Live System Architecture

```
Azure VM (135.235.139.80:8000)
│
├── fx_oanda/backend/api.py          FastAPI + WebSocket server
│     ├── /api/status                Full live snapshot (JSON)
│     ├── /api/account               OANDA account summary
│     ├── /api/kill                  Arm kill switch (flatten all)
│     ├── /api/disarm                Disarm kill switch
│     ├── /api/trader/start|stop     Toggle trading loop
│     └── /ws                        WebSocket (10s broadcast)
│
├── fx_oanda/runtime/live_trader.py  Core trading engine
│     ├── run_bar()                  Called every M30 close + 60s buffer
│     ├── _refresh_state()           Rebuild PCA/OU/HMM every 1h (TTL=2 bars)
│     └── _check_closed_trades()     Poll OANDA for SL/TP exits + PnL
│
├── fx_oanda/frontend/dist/          React dashboard (Vite build)
│     ├── MetricsBar                 Equity, Sharpe, drawdown, win rate
│     ├── EquityCurve                Trade-by-trade PnL chart
│     ├── RegimePanel                HMM regime + diagnostics
│     ├── PairGrid                   Per-pair z-scores and signals
│     ├── TradesPanel                Open / History tabs
│     ├── SignalLog                  Recent signal stream
│     ├── PnlByPair                  Bar chart by currency pair
│     └── KillSwitch                 Emergency flatten button
│
└── artifacts/
      ├── live_state.json            Written by run_bar() each bar (~30 min staleness)
      └── live_trades.json           Rolling 200-trade log
```

**Bar cycle timing:**
```
M30 bar closes (:00 or :30 UTC)
  + 60s buffer (OANDA propagation)
    → _check_closed_trades()     (SL/TP exits + PnL logging)
    → _refresh_state()           (PCA/OU/HMM rebuild if TTL expired — takes ~7 min on 62k bars)
    → build_candidate_signals()  (full filter stack)
    → recency check              (skip if latest signal > 1h old)
    → place_market_order()       (immediate fill, SL/TP attached)
    → write live_state.json + live_trades.json

NOTE: open_trades in UI updates only at next bar close (~30 min max lag after trade closes on OANDA)
```

---

## Operations

### Start / Stop
```bash
ssh -i ~/.ssh/perps_key.pem azureuser@135.235.139.80

sudo systemctl status fx1
sudo systemctl stop fx1
sudo systemctl start fx1
sudo systemctl restart fx1

# Live logs
journalctl -u fx1 -f
```

### Emergency Flatten
- Click "KILL" button on dashboard at `http://135.235.139.80:8000`
- Or: `curl -X POST http://135.235.139.80:8000/api/kill`

Writes `artifacts/kill_switch.json` → next `run_bar()` calls `flatten_all()` → closes all open trades.

### Re-deploy after code change
```bash
scp -i ~/.ssh/perps_key.pem fx_oanda/runtime/live_trader.py \
  azureuser@135.235.139.80:/home/azureuser/fx_oanda/runtime/live_trader.py

# Or full rsync
rsync -avz -e "ssh -i ~/.ssh/perps_key.pem" \
  --exclude '__pycache__/' --exclude 'venv/' --exclude 'artifacts/' \
  --exclude 'data/cache/' --exclude 'frontend/node_modules/' --exclude 'frontend/dist/' \
  fx_oanda/ azureuser@135.235.139.80:/home/azureuser/fx_oanda/

sudo systemctl restart fx1
```

### Credentials
Stored in `/home/azureuser/fx_oanda/.env`. Never committed to git.

---

## Known Limitations

1. **State rebuild latency**: Full PCA/OU/HMM refit on 62k bars takes ~7 minutes every hour. Orders placed 7 minutes into the new bar. At M30 this is acceptable but means the signal can be slightly stale.

2. **UI staleness on trade close**: `open_trades` in the dashboard reads from `live_state.json`, updated only at bar close. A trade closed by SL/TP mid-bar will show as open for up to 30 minutes.

3. **No live time-stop**: The backtest enforces a 6-bar (3h) time-stop. The live system relies entirely on OANDA-managed SL/TP. Trades that neither hit SL nor TP stay open indefinitely until one fires.

4. **Single-factor PCA**: Only PC1 extracted. If the G10 splits into two clusters (e.g., commodity vs safe-haven), residual signals degrade.

5. **Backtest vs live execution difference**: Backtest uses limit orders with assume_all_fills=true. Live uses market orders. Expect slightly higher transaction costs live (full spread on entry vs half-spread in backtest).

6. **Practice vs live spreads**: Practice spreads are slightly wider. Live account would have tighter spreads and better fill quality.
