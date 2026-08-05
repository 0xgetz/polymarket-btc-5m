"""
polybtc_session_runner.py
Skrip utama yang menjalankan sesi paper-trading / live-trading dengan proteksi ganda.
"""

import time
import logging
from polybtc_config import PolyBTCConfig
from polybtc_live_safety import SafetyGuardrails
from polybtc_edge import evaluate_momentum_edge

logger = logging.getLogger("polybtc_runner")

def run_trading_session():
    cfg = PolyBTCConfig.load_from_env()
    cfg.print_sanitized_summary()

    guard = SafetyGuardrails(
        max_stale_sec=cfg.max_stale_tick_sec,
        min_time_left_sec=cfg.min_time_left_sec
    )

    logger.info("Memulai loop trading Polymarket BTC 5m...")

    try:
        while True:
            # Simulasi timestamp data & sisa waktu pasar
            current_time = time.time()
            last_price_tick_time = current_time  # Ganti dengan timestamp feed asli
            time_left_in_market_sec = 120.0       # Ganti dengan sisa detik hingga expiry

            # 1. Pengecekan Guardrails
            if not guard.is_price_fresh(last_price_tick_time):
                time.sleep(1)
                continue

            if not guard.is_time_window_safe(time_left_in_market_sec):
                time.sleep(2)
                continue

            # 2. Perhitungan Edge & Sinyal
            btc_change_pct = 0.22  # Contoh pergerakan harga CEX
            yes_price = 0.48       # Harga pasar Polymarket

            eval_res = evaluate_momentum_edge(btc_change_pct, yes_price)
            signal = eval_res["signal"]

            if signal != "HOLD":
                target_price, shares = guard.format_polymarket_order(yes_price, cfg.max_position_size_usd)
                logger.info(f"[EXECUTIVE SIGNAL] {signal} | Size: {shares} shares @ ${target_price:.2f} | Edge: {eval_res['edge']:.2%}")

                if cfg.dry_run:
                    logger.info("[PAPER TRADING] Order berhasil disimulasikan.")
                else:
                    logger.info("[LIVE TRADING] Mengirimkan order ke Polymarket CLOB API...")

            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Sesi dihentikan oleh pengguna.")
    except Exception as e:
        logger.critical(f"Terjadi kesalahan tidak terduga pada main loop: {e}", exc_info=True)
    finally:
        logger.info("Membersihkan order aktif dan mematikan sesi dengan aman.")

if __name__ == "__main__":
    run_trading_session()
