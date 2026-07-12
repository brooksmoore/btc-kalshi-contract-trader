"""
Web dashboard for the Kalshi Bitcoin trading bot.
Runs a local HTTP server on port 8081 — open http://localhost:8081 in Chrome.

Usage:
    python3.11 deploy/webdash.py
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG_PATH = Path(__file__).parent.parent / "logs" / "bot.log"
SETTLEMENTS_PATH = Path(__file__).parent.parent / "logs" / "settlements.json"
PORT = 8081
SCAN_INTERVAL = 120  # seconds between bot cycles


def parse_log():
    trades = []
    signals = []
    cycle = 0
    last_cycle_time = ""
    last_btc_price = ""
    last_market = ""
    starting_bankroll = 1000.0
    current_bankroll = None
    daily_pnl = 0.0
    last_active_ts = None   # timestamp of last meaningful log line
    next_cycle_time = None  # estimated next wake-up

    try:
        text = LOG_PATH.read_text(errors="replace")
    except FileNotFoundError:
        return {}

    for line in text.splitlines():
        # Timestamp of every line
        ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        ts_str = ts_m.group(1) if ts_m else None

        if "EXECUTION:" in line:
            try:
                json_str = line[line.index("EXECUTION:") + 10:].strip()
                trade = json.loads(json_str)
                trade["local_ts"] = ts_str or ""  # attach log-line local timestamp
                trades.append(trade)
            except Exception:
                pass

        m = re.search(r"Engine initialized with \$([\d,]+\.?\d*)", line)
        if m:
            starting_bankroll = float(m.group(1).replace(",", ""))
            current_bankroll = starting_bankroll
            daily_pnl = 0.0

        m = re.search(r"Bankroll: \$([\d,]+\.\d+) \| Daily P&L: \$([+-]?[\d,]+\.\d+)", line)
        if m:
            current_bankroll = float(m.group(1).replace(",", ""))
            daily_pnl = float(m.group(2).replace(",", ""))

        m = re.search(r"Trading Cycle #(\d+) completed", line)
        if m:
            cycle = int(m.group(1))
            last_cycle_time = ts_str or ""
            last_active_ts = ts_str

        m = re.search(r"Sleeping (\d+)s until next cycle", line)
        if m and ts_str:
            last_active_ts = ts_str
            secs = int(m.group(1))
            try:
                sleep_start = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                next_cycle_time = sleep_start + timedelta(seconds=secs)
            except Exception:
                pass

        m = re.search(r"BTC price refreshed: \$([\d,]+\.\d+)", line)
        if m:
            last_btc_price = "$" + m.group(1)

        m = re.search(r"BTC market found: (\S+)", line)
        if m:
            last_market = m.group(1)

        if "orderbook_strategy - \x1b[32mINFO\x1b[0m -" in line or "orderbook_strategy - INFO -" in line:
            msg_m = re.search(r"orderbook_strategy.*?INFO.*? - (.+)", line)
            if msg_m:
                signals.append({"time": ts_str or "", "msg": msg_m.group(1)})

    # Determine bot status
    bot_alive = False
    status_txt = "STOPPED"
    status_cls = "stopped"

    if last_active_ts:
        try:
            age = (datetime.utcnow() - datetime.strptime(last_active_ts, "%Y-%m-%d %H:%M:%S")).total_seconds()
            if age < SCAN_INTERVAL + 60:  # allow 1 min grace past expected sleep
                bot_alive = True
                if next_cycle_time and next_cycle_time > datetime.utcnow():
                    wake = next_cycle_time.strftime("%H:%M:%S")
                    status_txt = f"Sleeping until {wake} UTC"
                    status_cls = "sleeping"
                else:
                    status_txt = "RUNNING"
                    status_cls = "running"
        except Exception:
            pass

    if current_bankroll is None:
        current_bankroll = starting_bankroll

    total = len(trades)
    buys = sum(1 for t in trades if t.get("side", "").upper() == "BUY")
    sells = total - buys
    avg_ev = sum(t.get("expected_value", 0) for t in trades) / total if total else 0
    exposure_usd = sum(t.get("price", 0) * t.get("count", 0) for t in trades)
    exposure_pct = (exposure_usd / starting_bankroll * 100) if starting_bankroll else 0
    total_pnl = current_bankroll - starting_bankroll

    # Load settlement results
    settlements = {}
    try:
        settlements = json.loads(SETTLEMENTS_PATH.read_text())
    except Exception:
        pass

    settled_pnl = sum(s["total_pnl"] for s in settlements.values() if s.get("result") in ("yes", "no"))
    settled_count = len([s for s in settlements.values() if s.get("result") in ("yes", "no")])
    wins  = len([s for s in settlements.values() if s.get("total_pnl", 0) > 0])
    losses = len([s for s in settlements.values() if s.get("total_pnl", 0) < 0])

    return {
        "cycle": cycle,
        "last_cycle_time": last_cycle_time,
        "last_btc_price": last_btc_price,
        "last_market": last_market,
        "status_txt": status_txt,
        "status_cls": status_cls,
        "trades": trades,
        "signals": signals[-20:],
        "settlements": settlements,
        "settled_pnl": settled_pnl,
        "settled_count": settled_count,
        "wins": wins,
        "losses": losses,
        "bankroll": {
            "starting": starting_bankroll,
            "current": current_bankroll,
            "daily_pnl": daily_pnl,
            "daily_pnl_cls": "pos" if daily_pnl >= 0 else "neg",
            "total_pnl": total_pnl,
            "total_pnl_cls": "pos" if total_pnl >= 0 else "neg",
            "exposure_usd": exposure_usd,
            "exposure_pct": exposure_pct,
        },
        "summary": {
            "total": total,
            "buys": buys,
            "sells": sells,
            "avg_ev": f"{avg_ev:+.1%}" if total else "—",
        },
    }


MONTHS = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
          'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}

def parse_expiry_utc(ticker):
    """Extract UTC expiry datetime from ticker like KXBTC15M-26APR082145-45."""
    m = re.search(r'-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})-', ticker)
    if not m:
        return None
    day, mon, yr, hh, mm = m.groups()
    try:
        return datetime(2000 + int(yr), MONTHS[mon], int(day), int(hh), int(mm))
    except Exception:
        return None


def build_html(data):
    if not data:
        return "<h1>Log file not found</h1>"

    now_utc = datetime.utcnow()
    trades_rows = ""
    for t in reversed(data["trades"][-50:]):
        # Use log-line local time stored alongside the trade, fallback to JSON ts
        local_ts = t.get("local_ts", "")
        display_time = local_ts[11:16] if len(local_ts) >= 16 else t.get("timestamp", "")[:16].replace("T", " ")[-5:]

        ticker = t.get("ticker", "")
        side   = t.get("side", "").upper()
        count  = t.get("count", 0)
        price  = t.get("price", 0)
        ev     = t.get("expected_value", 0)
        sc     = "buy" if side == "BUY" else "sell"
        ec     = "pos" if ev >= 0 else "neg"

        # Parse expiry and settlement result
        expiry = parse_expiry_utc(ticker)
        settlement = data["settlements"].get(ticker, {})
        result = settlement.get("result", "")
        trade_pnl = settlement.get("total_pnl")

        if result == "yes":
            won = (side == "BUY")
            outcome = "YES" if won else "NO"
            pnl_str = f"${trade_pnl:+.2f}" if trade_pnl is not None else ""
            pnl_cls = "pos" if (trade_pnl or 0) >= 0 else "neg"
            status = f"<span class='{pnl_cls}'>{'WIN' if won else 'LOSS'} ({pnl_str})</span>"
        elif result == "no":
            won = (side == "SELL")
            pnl_str = f"${trade_pnl:+.2f}" if trade_pnl is not None else ""
            pnl_cls = "pos" if (trade_pnl or 0) >= 0 else "neg"
            status = f"<span class='{pnl_cls}'>{'WIN' if won else 'LOSS'} ({pnl_str})</span>"
        elif expiry and expiry < now_utc:
            status = "<span style='color:#484f58'>Settling…</span>"
        elif expiry:
            status = f"<span class='buy'>OPEN — expires {expiry.strftime('%H:%M')} UTC</span>"
        else:
            status = "—"

        # Shorten ticker: strip prefix, show as "18:00 UTC"
        short_ticker = ticker.replace("KXBTC15M-", "")
        if expiry:
            short_ticker = expiry.strftime("%b %d %H:%M UTC")

        trades_rows += (
            f"<tr><td>{display_time}</td><td class='ticker'>{short_ticker}</td>"
            f"<td class='{sc}'>{side}</td><td>{count}</td>"
            f"<td>{price:.2f}</td><td class='{ec}'>{ev:+.1%}</td>"
            f"<td>{status}</td></tr>"
        )

    signals_rows = ""
    for sig in reversed(data["signals"]):
        msg = sig["msg"]
        sc  = "buy" if "BUY YES" in msg else ("sell" if "SELL NO" in msg else "")
        signals_rows += f"<tr><td>{sig['time']}</td><td class='{sc}'>{msg}</td></tr>"

    s  = data["summary"]
    b  = data["bankroll"]
    st = data["status_txt"]
    sc = data["status_cls"]

    settled_pnl   = data["settled_pnl"]
    settled_count = data["settled_count"]
    wins          = data["wins"]
    losses        = data["losses"]
    settlements   = data["settlements"]

    spnl_cls        = "pos" if settled_pnl >= 0 else "neg"
    bankroll_val    = f"${b['current']:,.2f}"
    daily_pnl_val   = f"${b['daily_pnl']:+,.2f}"
    settled_pnl_val = f"${settled_pnl:+,.2f}"
    exposure_val    = f"${b['exposure_usd']:.2f}"
    exposure_pct    = f"{b['exposure_pct']:.1f}%"
    daily_pnl_cls   = b["daily_pnl_cls"]
    total_pnl_val   = f"${b['total_pnl']:+,.2f}"
    total_pnl_cls   = b["total_pnl_cls"]
    btc_price       = data["last_btc_price"] or "—"
    last_market     = data["last_market"] or "—"
    last_cycle_time = data["last_cycle_time"] or "—"
    cycle_num       = data["cycle"]
    total_orders    = s["total"]
    buy_count       = s["buys"]
    sell_count      = s["sells"]
    avg_ev          = s["avg_ev"]
    now_str         = datetime.now().strftime("%H:%M:%S")

    no_trades   = '<tr><td colspan="7" style="color:#484f58;padding:20px">No trades yet</td></tr>'
    no_signals  = '<tr><td colspan="2" style="color:#484f58;padding:20px">No signals yet</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="10">
<title>BTC Bot Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1117; color: #c9d1d9; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; padding: 20px; }}
  h1 {{ color: #58a6ff; font-size: 18px; margin-bottom: 4px; }}
  h2 {{ color: #8b949e; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin: 20px 0 8px; }}
  .header {{ display: flex; align-items: center; gap: 16px; margin-bottom: 20px; border-bottom: 1px solid #21262d; padding-bottom: 12px; }}
  .badge {{ padding: 3px 12px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
  .running  {{ background: #1a4731; color: #3fb950; }}
  .sleeping {{ background: #1c2a3a; color: #58a6ff; }}
  .stopped  {{ background: #3d1f1f; color: #f85149; }}
  .stat-row {{ display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }}
  .stat {{ background: #161b22; border: 1px solid #21262d; border-radius: 6px; padding: 10px 16px; min-width: 120px; }}
  .stat .label {{ color: #8b949e; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; }}
  .stat .value {{ color: #e6edf3; font-size: 17px; font-weight: bold; margin-top: 3px; }}
  .stat .sub {{ color: #8b949e; font-size: 11px; }}
  .pos {{ color: #3fb950; }}
  .neg {{ color: #f85149; }}
  table {{ width: 100%; border-collapse: collapse; background: #161b22; border: 1px solid #21262d; border-radius: 6px; overflow: hidden; margin-bottom: 4px; }}
  th {{ background: #21262d; color: #8b949e; text-align: left; padding: 8px 12px; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
  td {{ padding: 7px 12px; border-top: 1px solid #21262d; }}
  tr:hover td {{ background: #1c2128; }}
  .ticker {{ color: #58a6ff; font-weight: bold; }}
  .buy  {{ color: #3fb950; }}
  .sell {{ color: #f85149; }}
  .refresh-note {{ color: #484f58; font-size: 11px; margin-top: 16px; }}
</style>
</head>
<body>

<div class="header">
  <h1>Kalshi BTC Bot — Paper Trading</h1>
  <span class="badge {sc}">{st}</span>
</div>

<div class="stat-row">
  <div class="stat">
    <div class="label">Bankroll</div>
    <div class="value">{bankroll_val}</div>
  </div>
  <div class="stat">
    <div class="label">Realized P&amp;L</div>
    <div class="value {spnl_cls}">{settled_pnl_val}</div>
    <div class="sub">{settled_count} settled &bull; {wins}W / {losses}L</div>
  </div>
  <div class="stat">
    <div class="label">Total P&amp;L</div>
    <div class="value {total_pnl_cls}">{total_pnl_val}</div>
  </div>
  <div class="stat">
    <div class="label">Exposure</div>
    <div class="value">{exposure_val}</div>
    <div class="sub">{exposure_pct} of bankroll</div>
  </div>
  <div class="stat">
    <div class="label">BTC Price</div>
    <div class="value">{btc_price}</div>
  </div>
  <div class="stat">
    <div class="label">Cycle</div>
    <div class="value">#{cycle_num}</div>
  </div>
  <div class="stat">
    <div class="label">Last Cycle</div>
    <div class="value" style="font-size:13px">{last_cycle_time}</div>
  </div>
  <div class="stat">
    <div class="label">Active Market</div>
    <div class="value" style="font-size:12px">{last_market}</div>
  </div>
  <div class="stat">
    <div class="label">Orders</div>
    <div class="value">{total_orders} <span class="sub">(<span class="buy">{buy_count}B</span> <span class="sell">{sell_count}S</span>)</span></div>
  </div>
  <div class="stat">
    <div class="label">Avg EV</div>
    <div class="value pos">{avg_ev}</div>
  </div>
</div>

<h2>Paper Orders (most recent first)</h2>
<table>
  <thead><tr><th>Time</th><th>Contract</th><th>Side</th><th>Qty</th><th>Price</th><th>EV</th><th>Status</th></tr></thead>
  <tbody>{trades_rows or no_trades}</tbody>
</table>

<h2>Recent Signals</h2>
<table>
  <thead><tr><th>Time</th><th>Signal</th></tr></thead>
  <tbody>{signals_rows or no_signals}</tbody>
</table>

<p class="refresh-note">Auto-refreshes every 10s &mdash; {now_str}</p>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = parse_log()
        html = build_html(data)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), Handler)
    print(f"Dashboard running at http://localhost:{PORT}")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
