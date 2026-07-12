"""Tests for live logger CSV export helpers."""

import json
from pathlib import Path

from polybtc_live_logger import export_jsonl_to_csv, row_to_csv_dict


def test_row_to_csv_dict_maps_fields():
    row = {
        "status": "obs",
        "ts": "2026-07-12T06:00:00Z",
        "slug": "btc-updown-5m-1",
        "seconds_left": 100,
        "btc_move_usd": 50,
        "btc_move_1m_usd": 5,
        "up_ask": 0.7,
        "dn_ask": 0.3,
        "spread": 0.01,
        "top_ask_notional": 40,
        "hour_utc": 6,
        "preflight_ok": False,
        "side": None,
        "entry_price": None,
        "edge": 0.01,
        "estimated_win_prob": 0.71,
        "stake_usd": None,
    }
    d = row_to_csv_dict(row)
    assert d["market_id"] == "btc-updown-5m-1"
    assert d["top_ask_notional_usd"] == 40
    assert d["btc_move_1m_usd"] == 5


def test_export_jsonl_to_csv(tmp_path: Path):
    src = tmp_path / "obs.jsonl"
    rows = [
        {
            "status": "obs",
            "ts": "2026-07-12T06:00:00Z",
            "slug": "m1",
            "seconds_left": 90,
            "btc_move_usd": 40,
            "up_ask": 0.65,
            "dn_ask": 0.35,
            "spread": 0.01,
            "top_ask_notional": 50,
            "preflight_ok": True,
            "side": "UP",
            "entry_price": 0.65,
        },
        {"status": "no_active_market", "ts": "x"},
    ]
    src.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    dest = tmp_path / "obs.csv"
    n = export_jsonl_to_csv(src, dest)
    assert n == 1
    text = dest.read_text(encoding="utf-8")
    assert "market_id" in text
    assert "m1" in text
