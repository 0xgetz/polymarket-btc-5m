#!/usr/bin/env python3
import argparse
import glob
import json
import os
import pathlib


def default_runtime_dir() -> str:
    return str(pathlib.Path(__file__).resolve().parents[1] / "runtime")


def parse_tail_json(path: str):
    txt = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    i = txt.rfind("\n{")
    if i == -1 and txt.startswith("{"):
        i = 0
    if i == -1:
        return None
    blob = txt[i + 1 :] if txt[i : i + 1] == "\n" else txt[i:]
    return json.loads(blob)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", default=default_runtime_dir())
    ap.add_argument("--mark", action="store_true")
    args = ap.parse_args()

    logs = sorted(glob.glob(os.path.join(args.runtime_dir, "polybtc_*.log")), key=os.path.getmtime, reverse=True)
    if not logs:
        print("NO_REPORT:no_logs")
        return

    latest = logs[0]
    marker = latest + ".reported"
    if os.path.exists(marker):
        print("NO_REPORT:already_reported")
        return

    pidfile = os.path.join(args.runtime_dir, "polybtc.pid")
    if os.path.exists(pidfile):
        try:
            pid = int(pathlib.Path(pidfile).read_text().strip())
            os.kill(pid, 0)
            print("NO_REPORT:running")
            return
        except Exception:
            pass

    try:
        obj = parse_tail_json(latest)
    except Exception as e:
        print(f"NO_REPORT:parse_error:{e}")
        return

    if not isinstance(obj, dict):
        print("NO_REPORT:no_json")
        return

    opened = obj.get("opened") or {}
    closed = obj.get("closed") or {}
    close_debug = obj.get("close_debug") or []

    lines = []
    lines.append("BTC5m run completed")
    lines.append(f"log: {latest}")
    lines.append(f"result: {obj.get('result')}")

    if opened:
        lines.append(
            f"open: {opened.get('side')} {opened.get('market_slug')} cost={opened.get('cost_usdc')} tx={opened.get('open_tx')}"
        )
    else:
        lines.append("open: none")

    if closed:
        lines.append(
            f"close: success={closed.get('close_success')} status={closed.get('close_status')} skipped={closed.get('close_skipped')} tx={closed.get('close_tx')}"
        )
    else:
        lines.append("close: none")

    lines.append(f"realized_cashflow_pnl_usdc: {obj.get('realized_cashflow_pnl_usdc')}")
    lines.append(f"close_debug_attempts: {len(close_debug)}")
    if obj.get("close_fallback"):
        lines.append(f"close_fallback: {obj.get('close_fallback')}")

    text = "\n".join(lines)
    print(text)

    if args.mark:
        pathlib.Path(marker).write_text("reported\n", encoding="utf-8")


if __name__ == "__main__":
    main()
