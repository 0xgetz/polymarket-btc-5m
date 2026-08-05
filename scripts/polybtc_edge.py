"""
polybtc_edge.py
Perhitungan sinyal momentum BTC dan estimasi slippage pasar.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("polybtc_edge")

def calculate_vwap_price(orderbook_bids_or_asks: list, target_shares: float) -> float:
    """Menghitung harga rata-rata tertimbang (VWAP) berdasarkan kedalaman orderbook."""
    accumulated_shares = 0.0
    accumulated_cost = 0.0

    for level in orderbook_bids_or_asks:
        price = float(level.get("price", 0))
        size = float(level.get("size", 0))

        needed = target_shares - accumulated_shares
        if needed <= 0:
            break

        take_size = min(size, needed)
        accumulated_shares += take_size
        accumulated_cost += take_size * price

    if accumulated_shares < target_shares:
        logger.warning("Orderbook kurang dalam untuk ukuran posisi yang diminta.")
        return 0.0

    return accumulated_cost / accumulated_shares

def evaluate_momentum_edge(
    cex_price_change_pct: float,
    polymarket_yes_price: float,
    threshold_pct: float = 0.15
) -> Dict[str, Any]:
    """
    Evaluasi sinyal perdagangan momentum:
    - Sinyal Beli UP jika perubahan harga BTC > threshold & opsi belum ter-priced in.
    """
    signal = "HOLD"
    edge = 0.0

    implied_probability = polymarket_yes_price
    model_probability = 0.50 + (cex_price_change_pct / 2.0)
    model_probability = max(0.05, min(0.95, model_probability))

    edge = model_probability - implied_probability

    if cex_price_change_pct > threshold_pct and edge > 0.05:
        signal = "BUY_UP"
    elif cex_price_change_pct < -threshold_pct and edge < -0.05:
        signal = "BUY_DOWN"

    return {
        "signal": signal,
        "edge": edge,
        "model_prob": model_probability,
        "implied_prob": implied_probability
    }
