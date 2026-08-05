"""
polybtc_live_safety.py
Modul pemeriksaan keamanan real-time sebelum mengeksekusi order.
"""

import time
import logging
from math import floor

logger = logging.getLogger("polybtc_live_safety")

class SafetyGuardrails:
    def __init__(self, max_stale_sec: float = 1.5, min_time_left_sec: int = 15):
        self.max_stale_sec = max_stale_sec
        self.min_time_left_sec = min_time_left_sec

    def is_price_fresh(self, last_tick_timestamp: float) -> bool:
        """Memeriksa apakah data harga CEX/Polymarket masih segar."""
        stale_duration = time.time() - last_tick_timestamp
        if stale_duration > self.max_stale_sec:
            logger.warning(f"[GUARDRAIL BLOCKED] Data harga terlalu lama ({stale_duration:.2f}s > {self.max_stale_sec}s)")
            return False
        return True

    def is_time_window_safe(self, time_remaining_sec: float) -> bool:
        """Memeriksa apakah sisa waktu pasar 5m masih mencukupi untuk entri."""
        if time_remaining_sec < self.min_time_left_sec:
            logger.warning(f"[GUARDRAIL BLOCKED] Sisa waktu terlalu dekat dengan expiry ({time_remaining_sec:.1f}s < {self.min_time_left_sec}s)")
            return False
        return True

    @staticmethod
    def format_polymarket_order(price: float, size_usd: float) -> tuple[float, float]:
        """
        Membulatkan harga dan jumlah opsi sesuai presisi Polymarket CLOB.
        - Harga dibulatkan ke 2 desimal ($0.01 - $0.99)
        - Shares dibulatkan ke angka bulat/desimal yang sesuai.
        """
        sanitized_price = round(max(0.01, min(0.99, price)), 2)
        shares = floor(size_usd / sanitized_price)
        if shares < 1:
            shares = 0.0
        return sanitized_price, float(shares)
