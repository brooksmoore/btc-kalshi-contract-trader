#!/usr/bin/env python3
"""Phase 0 settlement poller — mark captures whose markets resolved. No orders.

Matches open captures (by ticker) to market.result when available.
Only settles rows that already have external yes_ask as entry source.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from data.kalshi_client import KalshiClient
from measurement.settlement import record_settlement, settlement_count
from measurement.store import read_jsonl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phase0_settle")

CAPTURES = ROOT / "data" / "captures.jsonl"
SETTLEMENTS = ROOT / "data" / "settlements.jsonl"
DECISIONS = ROOT / "data" / "decisions.ndjson"


def _existing_settled_tickers() -> set[str]:
    return {str(r.get("ticker")) for r in read_jsonl(SETTLEMENTS)}


async def main_async(dry_run: bool) -> int:
    settings = get_settings()
    client = KalshiClient(
        api_key_id=settings.KALSHI_API_KEY_ID,
        private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
        base_url=settings.base_url,
        paper_trade=True,
    )
    settled_before = settlement_count(SETTLEMENTS)
    already = _existing_settled_tickers()
    # unique tickers from captures with measurement_ok
    by_ticker: dict[str, dict] = {}
    for row in read_jsonl(CAPTURES):
        if not row.get("measurement_ok"):
            continue
        t = str((row.get("market") or {}).get("ticker") or "")
        if t:
            by_ticker[t] = row

    n_new = 0
    try:
        for ticker, row in sorted(by_ticker.items()):
            if ticker in already:
                continue
            try:
                raw = await client.get_market(ticker)
                m = raw.get("market") if isinstance(raw, dict) and "market" in raw else raw
                result = (m or {}).get("result")
                if result not in ("yes", "no"):
                    continue
                book = row.get("book") or {}
                spot = row.get("spot") or {}
                yes_ask = book.get("yes_ask")
                if yes_ask is None:
                    continue
                if dry_run:
                    log.info("would settle %s result=%s ask=%s", ticker, result, yes_ask)
                    n_new += 1
                    continue
                record_settlement(
                    SETTLEMENTS,
                    ticker=ticker,
                    decision_id=f"btc:capture:{ticker}",
                    entry_price=float(yes_ask),
                    entry_price_source="kalshi_yes_ask",
                    result=str(result),
                    side="yes",
                    role="taker",
                    contracts=1,
                    spot_at_entry=spot.get("price_usd"),
                    kalshi_bid=book.get("yes_bid"),
                    kalshi_ask=book.get("yes_ask"),
                    extra={"hypothetical": True, "note": "phase0 touch settle, not an actual fill"},
                )
                n_new += 1
                log.info("settled %s result=%s", ticker, result)
            except Exception as exc:
                log.warning("settle %s failed: %s", ticker, exc)
    finally:
        await client.client.aclose()

    out = {
        "settlements_before": settled_before,
        "new": n_new,
        "settlements_after": settlement_count(SETTLEMENTS),
        "dry_run": dry_run,
    }
    print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
