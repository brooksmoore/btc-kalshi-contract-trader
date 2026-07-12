"""
Live dashboard for the Kalshi Bitcoin trading bot.
Parses bot.log and renders a refreshing terminal view.

Usage:
    python3.11 deploy/watch.py
"""

import os
import re
import json
import time
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "bot.log"
REFRESH_SECONDS = 5


def clear():
    os.system("clear")


def parse_log():
    trades = []
    signals = []
    cycle = 0
    last_cycle_time = None
    last_btc_price = None
    last_market = None
    rejected = []

    try:
        text = LOG_PATH.read_text(errors="replace")
    except FileNotFoundError:
        return {}, [], [], []

    for line in text.splitlines():
        # Paper trades / executions
        if "EXECUTION:" in line:
            try:
                json_str = line[line.index("EXECUTION:") + 10:].strip()
                data = json.loads(json_str)
                trades.append(data)
            except Exception:
                pass

        # Cycle counter
        m = re.search(r"Trading Cycle #(\d+) completed", line)
        if m:
            cycle = int(m.group(1))
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if ts_m:
                last_cycle_time = ts_m.group(1)

        # BTC price
        m = re.search(r"BTC price refreshed: \$([\d,]+\.\d+)", line)
        if m:
            last_btc_price = m.group(1)

        # Active market being scanned
        m = re.search(r"BTC market found: (\S+)", line)
        if m:
            last_market = m.group(1)

        # Strategy signals (INFO level from orderbook_strategy)
        m = re.search(r"orderbook_strategy - INFO - (.+)", line)
        if m:
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            ts = ts_m.group(1) if ts_m else ""
            signals.append((ts, m.group(1)))

        # Rejected signals
        if "Signal rejected by risk manager" in line or "below min threshold" in line:
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            ts = ts_m.group(1) if ts_m else ""
            msg_m = re.search(r"- (Signal rejected.*|Signal edge.*)", line)
            if msg_m:
                rejected.append((ts, msg_m.group(1)))

    meta = {
        "cycle": cycle,
        "last_cycle_time": last_cycle_time,
        "last_btc_price": last_btc_price,
        "last_market": last_market,
    }
    return meta, trades, signals[-10:], rejected[-5:]


def fmt_side(side):
    return "BUY " if side.upper() == "BUY" else "SELL"


def render():
    meta, trades, signals, rejected = parse_log()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w = 90

    clear()
    print("=" * w)
    print(f"  KALSHI BTC BOT — PAPER TRADING DASHBOARD          {now}")
    print("=" * w)

    # Status bar
    cycle = meta.get("cycle", 0)
    last_cycle = meta.get("last_cycle_time", "—")
    btc = meta.get("last_btc_price", "—")
    market = meta.get("last_market", "—")
    print(f"  Cycle: #{cycle}   Last: {last_cycle}   BTC: ${btc}   Market: {market}")
    print("-" * w)

    # Trades table
    print(f"  {'PAPER TRADES':^{w-4}}")
    print("-" * w)
    if trades:
        print(f"  {'Time':<20} {'Ticker':<30} {'Side':<5} {'Qty':>5}  {'Price':>6}  {'EV':>7}")
        print(f"  {'-'*18} {'-'*28} {'-'*4} {'---':>5}  {'-----':>6}  {'------':>7}")
        for t in trades[-15:]:
            ts = t.get("timestamp", "")[:19].replace("T", " ")
            ticker = t.get("ticker", "")[-25:]
            side = fmt_side(t.get("side", ""))
            count = t.get("count", 0)
            price = t.get("price", 0)
            ev = t.get("expected_value", 0)
            print(f"  {ts:<20} {ticker:<30} {side:<5} {count:>5}  {price:>6.2f}   {ev:>+.1%}")
    else:
        print("  No trades yet")
    print()

    # Recent signals
    print("-" * w)
    print(f"  RECENT SIGNALS (last 10)")
    print("-" * w)
    if signals:
        for ts, msg in signals[-10:]:
            print(f"  {ts}  {msg}")
    else:
        print("  No signals yet")
    print()

    # Summary
    print("-" * w)
    total = len(trades)
    buys = sum(1 for t in trades if t.get("side", "").upper() == "BUY")
    sells = total - buys
    avg_ev = sum(t.get("expected_value", 0) for t in trades) / total if total else 0
    print(f"  Total paper orders: {total}   BUY: {buys}   SELL: {sells}   Avg EV: {avg_ev:+.1%}")
    print("=" * w)
    print(f"  Refreshing every {REFRESH_SECONDS}s — Ctrl+C to quit")


if __name__ == "__main__":
    print("Starting dashboard... (Ctrl+C to quit)")
    try:
        while True:
            render()
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
