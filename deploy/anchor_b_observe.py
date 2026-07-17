#!/usr/bin/env python3
"""Anchor B observe-only harness — Deribit RN digital vs live Kalshi KXBTCD.

PAPER / OBSERVE ONLY. Does NOT:
  - open the Anchor-B efficacy window
  - emit counted umbrella `anchor_b` decisions
  - place orders

Logs rows to data/anchor_b_observe.jsonl with mode=observe, phase=pre_window.
Launchd: OFF by default (run manually).

Usage:
  python deploy/anchor_b_observe.py --once
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from data.kalshi_client import KalshiClient
from measurement.anchor_b_pricing import (
    DISAGREE_FLAG,
    fetch_deribit_chain,
    price_kalshi_kxbtcd,
)
from measurement.capture import book_for_ticker, fetch_btc_markets
from measurement.fees import net_ev_per_contract
from measurement.store import append_jsonl
from strategy.fair_value import parse_strike
from strategy.signal import DEFAULT_MIN_EDGE_USD, DEFAULT_MIN_PROB_EDGE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("anchor_b_observe")

OUT = ROOT / "data" / "anchor_b_observe.jsonl"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _kalshi_mid(book) -> float | None:
    yb = getattr(book, "yes_bid", None)
    ya = getattr(book, "yes_ask", None)
    if yb is not None and ya is not None:
        return (float(yb) + float(ya)) / 2.0
    if ya is not None:
        return float(ya)
    if yb is not None:
        return float(yb)
    return None


def _would_trade(p_fair: float, yes_bid, no_bid) -> dict:
    """Mirror Phase-1 maker-first gates WITHOUT logging a counted decision."""
    from strategy.signal import evaluate_entry

    d = evaluate_entry(
        p_fair=p_fair,
        yes_bid=yes_bid,
        no_bid=no_bid,
        min_edge_usd=DEFAULT_MIN_EDGE_USD,
        min_prob_edge=DEFAULT_MIN_PROB_EDGE,
    )
    return {
        "would_trade": d.get("action") == "entry",
        "action": d.get("action"),
        "side": d.get("side"),
        "entry_price": d.get("entry_price"),
        "net_ev": d.get("net_ev"),
        "reason": d.get("reason"),
    }


async def run_once() -> int:
    settings = get_settings()
    chain = fetch_deribit_chain()
    if not chain.ok:
        log.error("Deribit chain not ok: %s", chain.error)
        print(json.dumps({"ok": False, "error": chain.error, "n": 0}, indent=2))
        return 1

    log.info(
        "Deribit index=%.2f options=%d age=%.1fs",
        chain.index_usd, len(chain.options), chain.age_sec(),
    )

    client = KalshiClient(
        api_key_id=settings.KALSHI_API_KEY_ID,
        private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
        base_url=settings.base_url,
        paper_trade=True,
    )
    n_ok = n_skip = n_flag = 0
    samples: list[dict] = []
    try:
        markets = await fetch_btc_markets(client, settings)
        # Prefer KXBTCD near the Deribit index so samples are informative (not only deep OTM).
        def _sort_key(m: dict) -> float:
            t = str(m.get("ticker") or "")
            k = parse_strike(t)
            if k is None:
                return 1e18
            return abs(float(k) - float(chain.index_usd))

        markets = sorted(markets, key=_sort_key)
        for i, m in enumerate(markets):
            ticker = str(m.get("ticker") or "")
            if parse_strike(ticker) is None:
                n_skip += 1
                continue  # skip KXBTC15M etc.
            close_time = str(m.get("close_time") or "")
            if not close_time:
                n_skip += 1
                continue
            if i and i % 8 == 0:
                await asyncio.sleep(0.35)  # light Kalshi rate-limit courtesy
            book = await book_for_ticker(client, ticker, m)
            q = price_kalshi_kxbtcd(chain, ticker=ticker, close_time=close_time)
            mid = _kalshi_mid(book)
            if not q.ok or q.p_yes is None or mid is None:
                n_skip += 1
                row = {
                    "ts": _iso_now(),
                    "mode": "observe",
                    "phase": "pre_window",
                    "ticker": ticker,
                    "K": parse_strike(ticker),
                    "T": close_time,
                    "kalshi_mid": mid,
                    "anchor_b_prob": None,
                    "gap": None,
                    "would_trade": False,
                    "ok": False,
                    "error": q.error if not q.ok else "no kalshi mid",
                    "counted_decision": False,
                    "window_open": False,
                }
                append_jsonl(OUT, row)
                continue

            gap = float(q.p_yes) - float(mid)
            wt = _would_trade(float(q.p_yes), book.yes_bid, book.no_bid)
            if q.disagree_flag:
                n_flag += 1
            row = {
                "ts": _iso_now(),
                "mode": "observe",
                "phase": "pre_window",
                "ticker": ticker,
                "K": q.strike,
                "T": close_time,
                "kalshi_mid": round(float(mid), 4),
                "anchor_b_prob": round(float(q.p_yes), 6),
                "p_n_d2": round(float(q.p_n_d2), 6) if q.p_n_d2 is not None else None,
                "p_bl": round(float(q.p_bl), 6) if q.p_bl is not None else None,
                "disagree": round(float(q.disagree), 6) if q.disagree is not None else None,
                "disagree_flag": q.disagree_flag,
                "gap": round(gap, 6),
                "iv_used": round(float(q.iv_used), 6) if q.iv_used is not None else None,
                "spot_deribit": q.spot,
                "tte_years": q.tte_years,
                **{k: wt[k] for k in ("would_trade", "action", "side", "entry_price", "net_ev", "reason")},
                "ok": True,
                "counted_decision": False,
                "window_open": False,
                "experiment_id": "btc-anchor-b-observe-pre-window",
            }
            append_jsonl(OUT, row)
            n_ok += 1
            if len(samples) < 8:
                samples.append({
                    "ticker": ticker,
                    "kalshi_mid": row["kalshi_mid"],
                    "anchor_b_prob": row["anchor_b_prob"],
                    "gap": row["gap"],
                    "p_bl": row["p_bl"],
                    "disagree": row["disagree"],
                    "would_trade": row["would_trade"],
                })
    finally:
        await client.client.aclose()

    out = {
        "ok": True,
        "n_priced": n_ok,
        "n_skip": n_skip,
        "n_disagree_flag": n_flag,
        "disagree_threshold": DISAGREE_FLAG,
        "deribit_index": chain.index_usd,
        "out": str(OUT),
        "samples": samples,
        "window_open": False,
        "counted_decisions": False,
    }
    print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Anchor B observe-only (no counted trades)")
    ap.add_argument("--once", action="store_true", default=True)
    args = ap.parse_args()
    return asyncio.run(run_once())


if __name__ == "__main__":
    raise SystemExit(main())
