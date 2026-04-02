from __future__ import annotations


def fractional_kelly(p_win: float, rr_ratio: float, fraction: float = 0.25, max_risk: float = 0.02) -> float:
    p_lose = 1.0 - p_win
    rr_ratio = max(rr_ratio, 1e-6)
    full_kelly = (p_win * rr_ratio - p_lose) / rr_ratio
    full_kelly = max(full_kelly, 0.0)
    return min(full_kelly * fraction, max_risk)


def vol_adjusted_leverage(har_rv: float, vol_ref: float, max_leverage: float = 50.0) -> float:
    """Inverse-volatility leverage: scale leverage up when vol is low, down when vol is high.

    leverage = min(vol_ref / har_rv, max_leverage)

    At the median signal har_rv (~0.00043) with vol_ref=0.015 this gives ~35x.
    High-vol pairs (har_rv ~0.001) get ~15x; low-vol outliers are capped at max_leverage.
    """
    if har_rv <= 1e-10:
        return max_leverage
    return min(vol_ref / har_rv, max_leverage)


def compute_position_size(
    pair_margin: float,
    leverage: float,
    entry_price: float,
) -> int:
    """Units = margin × leverage / price.  Simple and exact — sizing is fully determined
    by the per-pair margin budget and the vol-adjusted leverage."""
    if entry_price <= 1e-8 or leverage <= 0.0 or pair_margin <= 0.0:
        return 0
    return int(pair_margin * leverage / entry_price)
