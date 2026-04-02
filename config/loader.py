from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "config.yaml"


def _deep_merge(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None, overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if overrides:
        cfg = _deep_merge(cfg, overrides)

    env = cfg.setdefault("oanda", {}).get("environment", "practice")
    base_default = "https://api-fxpractice.oanda.com" if env == "practice" else "https://api-fxtrade.oanda.com"
    cfg["oanda"]["account_id"] = cfg["oanda"].get("account_id") or os.getenv("OANDA_ACCOUNT_ID", "")
    cfg["oanda"]["api_key"] = cfg["oanda"].get("api_key") or os.getenv("OANDA_API_TOKEN", "")
    cfg["oanda"]["base_url"] = cfg["oanda"].get("base_url") or os.getenv("OANDA_API_URL", base_default)

    for rel_key in ["cache_dir"]:
        cfg["data"][rel_key] = str((PACKAGE_ROOT / cfg["data"][rel_key]).resolve())

    for rel_key in ["artifact_dir", "backtest_dir", "model_dir", "dashboard_state", "trade_log", "kill_switch"]:
        cfg["paths"][rel_key] = str((PACKAGE_ROOT / cfg["paths"][rel_key]).resolve())

    return cfg


def ensure_dirs(cfg: Dict[str, Any]) -> None:
    Path(cfg["data"]["cache_dir"]).mkdir(parents=True, exist_ok=True)
    for key in ["artifact_dir", "backtest_dir", "model_dir"]:
        Path(cfg["paths"][key]).mkdir(parents=True, exist_ok=True)
    for key in ["dashboard_state", "trade_log", "kill_switch"]:
        Path(cfg["paths"][key]).parent.mkdir(parents=True, exist_ok=True)

