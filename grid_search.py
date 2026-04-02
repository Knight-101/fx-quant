"""
Grid search: z_entry × session_end × time_stop × z_tp — maximize annualised return with PF > 1.
State built once; only signal generation + backtest swept.
"""
from __future__ import annotations

import copy

from fx_oanda.backtest.engine import FX1Backtester
from fx_oanda.config.loader import ensure_dirs, load_config
from fx_oanda.data.fetch_oanda import load_cache
from fx_oanda.strategy.pipeline import build_candidate_signals, build_strategy_state

cfg = load_config()
ensure_dirs(cfg)
data = load_cache(cfg)

print("Building state (runs once)...")
state = build_strategy_state(data, cfg)
train_end = state.train_end_time
test_end  = state.returns.index[-1]
test_years = (test_end - train_end).days / 365.25
print(f"Train → {train_end}  |  Test → {test_end}  ({test_years:.2f} yr)\n")

z_entry_vals   = [1.0, 1.2, 1.5]
session_ends   = [8, 10, 12]
time_stop_vals = [4, 6, 8]
z_tp_vals      = [0.3, 0.5]

header = (
    f"{'z_ent':>6} {'sess':>5} {'tstop':>6} {'z_tp':>5} "
    f"{'trd':>4} {'WR%':>5} {'PF':>6} "
    f"{'ann%':>7} {'DD%':>7} {'sh':>6} {'avg_lev':>8}"
)
print(header)
print("-" * len(header))

results = []

for z_entry in z_entry_vals:
    for session_end in session_ends:
        c = copy.deepcopy(cfg)
        c["signals"]["z_entry_weak"]    = z_entry
        c["signals"]["z_entry_strong"]  = z_entry + 0.3
        c["signals"]["session_end_utc"] = session_end
        c["signals"]["kappa_min"]       = 0.0

        sigs = build_candidate_signals(state, c)
        if sigs.empty:
            continue
        test = sigs[sigs.index > train_end].copy()
        if test.empty:
            continue

        for time_stop in time_stop_vals:
            for z_tp in z_tp_vals:
                c2 = copy.deepcopy(c)
                c2["execution"]["time_stop_bars"] = time_stop
                c2["signals"]["z_tp"] = z_tp

                result = FX1Backtester(c2).run(test, state.prices)
                m = result.summary

                pf   = m["profit_factor"]
                ret  = m["total_return"]
                ann  = ((1 + ret) ** (1 / test_years) - 1) * 100
                dd   = m["max_drawdown"] * 100
                wr   = m["win_rate"] * 100
                sh   = m["sharpe"]
                tr   = m["total_trades"]
                alev = m["avg_leverage"]

                row = (
                    f"{z_entry:>6.1f} {session_end:>5} {time_stop:>6} {z_tp:>5.1f} "
                    f"{tr:>4} {wr:>5.1f} {pf:>6.3f} "
                    f"{ann:>7.2f} {dd:>7.2f} {sh:>6.2f} {alev:>8.1f}"
                )
                print(row)
                results.append((ann, sh, pf, tr, row))

good = [(a, s, p, t, r) for a, s, p, t, r in results if p > 1.0 and t >= 30]
good.sort(reverse=True)

print(f"\n{'='*len(header)}")
print("TOP 10 (PF>1, ≥30 trades, ranked by annualised return %):")
for a, s, p, t, r in good[:10]:
    print(r)
