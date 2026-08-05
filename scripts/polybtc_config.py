"""
polybtc_config.py
Modul manajemen konfigurasi dan validasi environment variabel secara aman.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("polybtc_config")

@dataclass
class PolyBTCConfig:
    polygon_private_key: str
    polymarket_api_key: str
    polymarket_secret: str
    polymarket_passphrase: str
    max_position_size_usd: float = 10.0
    max_drawdown_pct: float = 0.05
    max_stale_tick_sec: float = 1.5
    min_time_left_sec: int = 15
    dry_run: bool = True

    @classmethod
    def load_from_env(cls) -> "PolyBTCConfig":
        dry_run = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
        
        private_key = os.getenv("POLYGON_PRIVATE_KEY", "")
        api_key = os.getenv("POLYMARKET_API_KEY", "")
        secret = os.getenv("POLYMARKET_SECRET", "")
        passphrase = os.getenv("POLYMARKET_PASSPHRASE", "")

        if not dry_run:
            missing = []
            if not private_key: missing.append("POLYGON_PRIVATE_KEY")
            if not api_key: missing.append("POLYMARKET_API_KEY")
            if missing:
                raise ValueError(f"Variabel lingkungan kritis tidak ditemukan untuk Mode Live: {', '.join(missing)}")

        return cls(
            polygon_private_key=private_key,
            polymarket_api_key=api_key,
            polymarket_secret=secret,
            polymarket_passphrase=passphrase,
            max_position_size_usd=float(os.getenv("MAX_POSITION_SIZE_USD", "10.0")),
            max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", "0.05")),
            max_stale_tick_sec=float(os.getenv("MAX_STALE_TICK_SEC", "1.5")),
            min_time_left_sec=int(os.getenv("MIN_TIME_LEFT_SEC", "15")),
            dry_run=dry_run
        )

    def print_sanitized_summary(self):
        """Menampilkan ringkasan konfigurasi tanpa membocorkan kunci rahasia."""
        def mask(val: str) -> str:
            if not val or len(val) < 8:
                return "***"
            return f"{val[:4]}...{val[-4:]}"

        logger.info("=== CONFIGURATION SUMMARY ===")
        logger.info(f"Dry Run Mode         : {self.dry_run}")
        logger.info(f"Max Position Size    : ${self.max_position_size_usd:.2f}")
        logger.info(f"Max Drawdown Limit   : {self.max_drawdown_pct * 100:.1f}%")
        logger.info(f"Max Stale Tick       : {self.max_stale_tick_sec} detik")
        logger.info(f"Min Time Left        : {self.min_time_left_sec} detik")
        logger.info(f"Polygon Private Key  : {mask(self.polygon_private_key)}")
        logger.info(f"Polymarket API Key   : {mask(self.polymarket_api_key)}")
        logger.info("=============================")
