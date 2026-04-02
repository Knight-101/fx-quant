from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def write_backtest_artifacts(run_dir: str | Path, result, signals_df: pd.DataFrame, diagnostics: dict) -> dict:
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    result.trades.to_csv(run_path / "trades.csv", index=False)
    result.equity_curve.to_csv(run_path / "equity_curve.csv", index=False)
    signals_df.to_csv(run_path / "signals.csv")
    summary = {"metrics": result.summary, "diagnostics": diagnostics}
    (run_path / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary

