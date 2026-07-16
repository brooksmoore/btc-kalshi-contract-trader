#!/usr/bin/env python3
"""Phase 1 paper runner — cost-honest baseline strategy (anchor A: spot + realized vol).

PAPER ONLY. Never places real orders (emits umbrella decisions + a positions log; a separate
settle poller resolves them against real prices). Prices KXBTCD strike contracts with a driftless
digital fair value, trades maker-first only when net-of-fee EV clears a floor. Per
EFFICACY_TEST_BTC_2026-07-11.md: no edge claim before KILL_N; FLOORED if net_ev_oos <= 0.

Independent-bet discipline (2026-07-16): at most one counted entry per ticker while that
position is open (unsettled). Re-logging the same open contract every cycle is forbidden.

Usage (from bot root):
  python deploy/run_phase1.py --once
  python deploy/run_phase1.py --loops 0 --interval 120      # 0 = run forever
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from data.kalshi_client import KalshiClient
from decision_emit import emit_decision_safe
from measurement.capture import book_for_ticker, fetch_btc_markets
from measurement.phase1_dedup import (
    mark_opened,
    open_tickers_from_paths,
    should_count_new_entry,
)
from measurement.spot import fetch_btc_spot_usd
from strategy.runner import build_strategy_decision, price_and_signal_market

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("phase1")

DATA = ROOT / "data"
DECISIONS_PATH = DATA / "decisions.ndjson"
SPOT_HISTORY = DATA / "phase1_spot_history.jsonl"
POSITIONS_LOG = DATA / "phase1_positions.jsonl"
SETTLEMENTS_PATH = DATA / "phase1_settlements.jsonl"
_MAX_HISTORY = 240  # rolling spot samples used for realized vol
_MIN_SAMPLES = 20   # require a stable series before trusting vol (~40 min at 120s) — no trades before


def _load_spot_history() -> list[float]:
    if not SPOT_HISTORY.exists():
        return []
    out: list[float] = []
    for line in SPOT_HISTORY.read_text().splitlines()[-_MAX_HISTORY:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(float(json.loads(line)["price_usd"]))
        except (ValueError, KeyError):
            continue
    return out


def _append_spot(price: float, ts: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with SPOT_HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"price_usd": price, "ts": ts}) + "\n")


def load_open_tickers() -> set[str]:
    """Tickers with an unsettled counted position (disk truth)."""
    return open_tickers_from_paths(POSITIONS_LOG, SETTLEMENTS_PATH)


def count_entry_if_new(
    decision: dict[str, Any],
    *,
    open: set[str],
    spot_usd: float,
    vol_annual: float,
    decisions_path: Path = DECISIONS_PATH,
    positions_path: Path = POSITIONS_LOG,
    emit: bool = True,
) -> Optional[dict[str, Any]]:
    """Log one counted entry if ticker is not already open. Pure gate + optional I/O.

    Returns the umbrella decision record if counted, else None (already open / not entry).
    Mutates `open` in place when a new entry is counted.
    """
    if decision.get("action") != "entry":
        return None
    ticker = str(decision.get("ticker") or "")
    if not should_count_new_entry(ticker, open):
        return None
    rec = build_strategy_decision(decision, spot_usd=spot_usd, vol_annual=vol_annual)
    if rec is None:
        return None
    if emit:
        emit_decision_safe(decisions_path, rec)
        positions_path.parent.mkdir(parents=True, exist_ok=True)
        with positions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": rec.get("ts"),
                "ticker": decision["ticker"],
                "side": decision["side"],
                "entry_price": decision["entry_price"],
                "p_fair": decision["p_fair"],
                "net_ev": decision.get("net_ev"),
                "decision_id": rec.get("decision_id"),
            }) + "\n")
    mark_opened(open, ticker)
    return rec


async def _one_cycle(
    client,
    settings,
    *,
    interval_seconds: float,
    open: set[str],
) -> dict:
    from strategy.fair_value import realized_vol_annual, vol_is_plausible

    spot = fetch_btc_spot_usd()
    if not getattr(spot, "ok", False) and not getattr(spot, "price_usd", None):
        log.warning("spot fetch failed; skipping cycle (fail-closed, no trades)")
        return {"entries": 0, "rejects": 0, "skips": 0, "already_open": 0, "vol": None}

    spot_usd = float(spot.price_usd)
    _append_spot(spot_usd, getattr(spot, "ts", ""))
    history = _load_spot_history()
    if len(history) < _MIN_SAMPLES:
        log.info("accumulating spot history (%d/%d) — no trades yet", len(history), _MIN_SAMPLES)
        return {"entries": 0, "rejects": 0, "skips": 0, "already_open": 0, "vol": None}
    vol = realized_vol_annual(history, interval_seconds=interval_seconds)
    if not vol_is_plausible(vol):
        log.info(
            "realized vol not usable (vol=%s, history=%d) — no trades this cycle (fail-closed)",
            vol, len(history),
        )
        return {"entries": 0, "rejects": 0, "skips": 0, "already_open": 0, "vol": vol}

    markets = await fetch_btc_markets(client, settings)
    now_ts = time.time()
    entries = rejects = skips = already_open = 0
    for m in markets:
        ticker = str(m.get("ticker") or "")
        book = await book_for_ticker(client, ticker, m)
        d = price_and_signal_market(m, book, spot_usd=spot_usd, vol_annual=vol, now_ts=now_ts)
        act = d.get("action")
        if act == "skip":
            skips += 1
            continue
        if act == "reject":
            rejects += 1
            continue
        # entry signal — only count if ticker not already open
        if not should_count_new_entry(str(d.get("ticker") or ""), open):
            already_open += 1
            continue
        rec = count_entry_if_new(d, open=open, spot_usd=spot_usd, vol_annual=vol)
        if rec is None:
            already_open += 1
            continue
        entries += 1
    return {
        "entries": entries,
        "rejects": rejects,
        "skips": skips,
        "already_open": already_open,
        "vol": round(vol, 4),
    }


async def _main_async(args) -> int:
    settings = get_settings()
    loops = 0
    open = load_open_tickers()
    log.info("phase1 open positions at start: %d tickers", len(open))
    client = KalshiClient(
        api_key_id=settings.KALSHI_API_KEY_ID,
        private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
        base_url=settings.base_url,
        paper_trade=True,  # belt-and-suspenders: this runner never places real orders
    )
    async with client:
        while True:
            try:
                # Disk is source of truth each cycle so settle poller frees tickers.
                open = load_open_tickers()
                res = await _one_cycle(
                    client, settings, interval_seconds=float(args.interval), open=open,
                )
                log.info(
                    "phase1 cycle: entries=%d already_open=%d rejects=%d skips=%d vol=%s",
                    res["entries"], res["already_open"], res["rejects"], res["skips"], res["vol"],
                )
            except Exception:
                log.exception("phase1 cycle failed (continuing)")
            loops += 1
            if args.once or (args.loops and loops >= args.loops):
                break
            await asyncio.sleep(float(args.interval))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1 paper strategy runner (never places orders)")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("--loops", type=int, default=0, help="max cycles (0 = forever)")
    ap.add_argument("--interval", type=float, default=120.0, help="seconds between cycles")
    args = ap.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
