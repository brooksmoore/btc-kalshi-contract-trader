"""One Phase-0 capture cycle: independent spot + Kalshi BTC books → JSONL + decisions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from measurement.book import BookSnap, market_top_of_book_from_market_dict, parse_orderbook
from measurement.fees import maker_fee_per_contract, taker_fee_per_contract
from measurement.spot import SpotQuote, fetch_btc_spot_usd
from measurement.store import append_jsonl

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE_PATH = _BOT_ROOT / "data" / "captures.jsonl"
DEFAULT_DECISIONS_PATH = _BOT_ROOT / "data" / "decisions.ndjson"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unwrap_markets(resp: Any) -> list[dict]:
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for key in ("markets", "market", "data"):
            if key in resp and isinstance(resp[key], list):
                return resp[key]
            if key in resp and isinstance(resp[key], dict):
                return [resp[key]]
        # single market
        if "ticker" in resp:
            return [resp]
    return []


async def fetch_btc_markets(client: Any, settings: Any) -> list[dict]:
    """Pull open BTC-related markets (15m + daily prefixes)."""
    series_list = [
        getattr(settings, "BTC_15M_TICKER", "KXBTC15M"),
        getattr(settings, "BTC_DAILY_TICKER", "KXBTCD"),
        getattr(settings, "BTC_GENERAL_TICKER", "KXBTC"),
    ]
    seen: set[str] = set()
    out: list[dict] = []
    for series in series_list:
        try:
            raw = await client.get_markets(series_ticker=series, status="open", limit=50)
            for m in _unwrap_markets(raw):
                t = str(m.get("ticker") or "")
                if t and t not in seen:
                    seen.add(t)
                    out.append(m)
        except Exception as exc:
            logger.warning("get_markets(%s) failed: %s", series, exc)
    return out


async def book_for_ticker(client: Any, ticker: str, market: dict) -> BookSnap:
    try:
        raw_ob = await client.get_orderbook(ticker)
        snap = parse_orderbook(ticker, raw_ob if isinstance(raw_ob, dict) else {})
        if snap.yes_bid is not None or snap.yes_ask is not None:
            return snap
    except Exception as exc:
        logger.debug("orderbook %s failed: %s", ticker, exc)
    return market_top_of_book_from_market_dict(ticker, market)


def build_capture_row(
    *,
    spot: SpotQuote,
    market: dict[str, Any],
    book: BookSnap,
) -> dict[str, Any]:
    ticker = str(market.get("ticker") or book.ticker)
    yes_ask = book.tradeable_yes_buy()
    fees = {}
    if yes_ask is not None:
        fees = {
            "taker_fee_yes_ask": taker_fee_per_contract(yes_ask),
            "maker_fee_yes_bid": maker_fee_per_contract(book.yes_bid or yes_ask),
        }
    return {
        "ts": _iso_now(),
        "phase": "0",
        "spot": {
            "price_usd": spot.price_usd if spot.ok else None,
            "source": spot.source,
            "ok": spot.ok,
            "error": spot.error,
            "latency_ms": spot.latency_ms,
            "ts": spot.ts,
        },
        "market": {
            "ticker": ticker,
            "title": market.get("title") or market.get("subtitle"),
            "status": market.get("status"),
            "close_time": market.get("close_time") or market.get("expected_expiration_time"),
            "volume": market.get("volume") or market.get("volume_fp"),
            "open_interest": market.get("open_interest"),
            "result": market.get("result"),
        },
        "book": {
            "yes_bid": book.yes_bid,
            "yes_ask": book.yes_ask,
            "no_bid": book.no_bid,
            "no_ask": book.no_ask,
            "yes_mid": book.yes_mid,
            "raw_keys": book.raw_keys[:20],
        },
        "fees_at_touch": fees,
        "measurement_ok": bool(
            spot.ok and (book.yes_bid is not None or book.yes_ask is not None)
        ),
    }


def emit_hold_decision_for_capture(
    row: dict[str, Any],
    *,
    decisions_path: Path = DEFAULT_DECISIONS_PATH,
) -> bool:
    """Log a hold observation with real book ask as ref (not a trade signal).

    Phase 0 does not claim edge; kind=hold documents that we *could* trade at ask.
    """
    from decision_emit import build_decision_record, emit_decision_safe

    book = row.get("book") or {}
    spot = row.get("spot") or {}
    mkt = row.get("market") or {}
    yes_ask = book.get("yes_ask")
    if yes_ask is None:
        return False
    if not spot.get("ok"):
        return False

    rec = build_decision_record(
        kind="hold",
        instrument=str(mkt.get("ticker")),
        reason="phase0 capture: real yes_ask + independent spot (no trade)",
        mode="paper",
        side="buy",
        qty=0.0,
        ref_price=float(yes_ask),
        entry_price_source="kalshi_yes_ask",
        prediction={"type": "none"},
        benchmarks={
            "BTC_USD": float(spot["price_usd"]),
        },
        lineage={
            "trigger": "phase0_capture",
            "entry_price_source": "kalshi_yes_ask",
            "spot_source": spot.get("source"),
            "yes_bid": book.get("yes_bid"),
            "yes_ask": book.get("yes_ask"),
            "llm_calls": 0,
            "llm_cost_usd": 0.0,
        },
        experiment_id="btc-phase0-measurement",
    )
    return emit_decision_safe(decisions_path, rec)


async def run_capture_cycle(
    client: Any,
    settings: Any,
    *,
    capture_path: Path = DEFAULT_CAPTURE_PATH,
    decisions_path: Path = DEFAULT_DECISIONS_PATH,
    max_markets: int = 15,
    emit_decisions: bool = True,
) -> dict[str, Any]:
    """One full capture cycle. Never places orders."""
    spot = fetch_btc_spot_usd()
    markets = await fetch_btc_markets(client, settings)
    markets = markets[:max_markets]

    rows: list[dict[str, Any]] = []
    decisions_emitted = 0
    for m in markets:
        ticker = str(m.get("ticker") or "")
        if not ticker:
            continue
        book = await book_for_ticker(client, ticker, m)
        row = build_capture_row(spot=spot, market=m, book=book)
        append_jsonl(capture_path, row)
        rows.append(row)
        if emit_decisions and row.get("measurement_ok"):
            if emit_hold_decision_for_capture(row, decisions_path=decisions_path):
                decisions_emitted += 1

    summary = {
        "ts": _iso_now(),
        "spot_ok": spot.ok,
        "spot_usd": spot.price_usd if spot.ok else None,
        "markets_seen": len(markets),
        "captures_written": len(rows),
        "measurement_ok_count": sum(1 for r in rows if r.get("measurement_ok")),
        "decisions_emitted": decisions_emitted,
        "capture_path": str(capture_path),
    }
    logger.info("phase0 capture: %s", summary)
    return summary
