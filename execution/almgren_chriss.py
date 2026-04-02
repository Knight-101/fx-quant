from __future__ import annotations


def fx_urgency_score(z_score: float, hawkes_decay_rate: float, cfg: dict) -> float:
    z_norm = min(abs(z_score) / max(cfg["signals"]["z_entry_strong"], 1e-6), 1.5)
    urgency = 0.5 * z_norm + 0.5 * min(max(hawkes_decay_rate, 0.0), 1.0)
    return float(urgency)


def entry_order_type(urgency: float) -> tuple[str, int]:
    if urgency >= 0.75:
        return "MARKET", 0
    if urgency >= 0.55:
        return "LIMIT", 2
    return "SKIP", 0

