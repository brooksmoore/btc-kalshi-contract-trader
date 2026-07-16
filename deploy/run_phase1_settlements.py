#!/usr/bin/env python3
"""Phase-1 settlement poller — join phase1_positions → market result → fee-honest rows.

PAPER ONLY. Never places orders. Writes data/phase1_settlements.jsonl keyed by decision_id.
Reuses measurement.settlement.record_settlement + measurement.fees (maker).
Contamination: only post-2026-07-13 entries are eligible.
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
from measurement.phase1_score import (
    entry_price_source_for_side,
    is_post_fix,
    load_phase1_entries,
    settled_decision_ids,
    tte_bucket_label,
    tte_days_at_entry,
)
from measurement.settlement import record_settlement, settlement_count
from measurement.spot import fetch_btc_spot_usd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phase1_settle")

POSITIONS = ROOT / "data" / "phase1_positions.jsonl"
SETTLEMENTS = ROOT / "data" / "phase1_settlements.jsonl"


async def main_async(*, dry_run: bool, limit: int | None) -> int:
    settings = get_settings()
    client = KalshiClient(
        api_key_id=settings.KALSHI_API_KEY_ID,
        private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
        base_url=settings.base_url,
        paper_trade=True,
    )
    already = settled_decision_ids(SETTLEMENTS)
    entries = load_phase1_entries(POSITIONS, require_post_fix=True)
    open_entries = [e for e in entries if str(e.get("decision_id")) not in already]
    if limit is not None:
        open_entries = open_entries[:limit]

    # Cache market lookups by ticker (many positions re-hit the same market).
    market_cache: dict[str, dict] = {}
    n_new = 0
    n_pending = 0
    n_skip = 0
    spot_at_settle: float | None = None
    try:
        spot = fetch_btc_spot_usd()
        if getattr(spot, "ok", False) and spot.price_usd is not None:
            spot_at_settle = float(spot.price_usd)
    except Exception as exc:
        log.warning("spot_at_settle unavailable (continuing): %s", exc)

    try:
        for row in open_entries:
            decision_id = str(row.get("decision_id") or "")
            ticker = str(row.get("ticker") or "")
            if not decision_id or not ticker:
                n_skip += 1
                continue
            if not is_post_fix(row.get("ts")):
                n_skip += 1
                continue

            if ticker not in market_cache:
                try:
                    raw = await client.get_market(ticker)
                    m = raw.get("market") if isinstance(raw, dict) and "market" in raw else raw
                    market_cache[ticker] = m or {}
                except Exception as exc:
                    log.warning("get_market %s failed: %s", ticker, exc)
                    market_cache[ticker] = {}

            m = market_cache[ticker]
            result = (m or {}).get("result")
            if result not in ("yes", "no"):
                n_pending += 1
                continue

            side = str(row.get("side") or "yes").lower()
            entry_price = float(row["entry_price"])
            src = entry_price_source_for_side(side)
            close_time = (m or {}).get("close_time") or (m or {}).get("expiration_time")
            tte = tte_days_at_entry(row.get("ts"), str(close_time) if close_time else None)
            tte_b = tte_bucket_label(tte)

            if dry_run:
                log.info(
                    "would settle %s result=%s side=%s entry=%s tte_d=%s",
                    decision_id[:48], result, side, entry_price, tte,
                )
                n_new += 1
                continue

            # p_fair is logged under extra for audit only — PnL uses market result + fees only.
            record_settlement(
                SETTLEMENTS,
                ticker=ticker,
                decision_id=decision_id,
                entry_price=entry_price,
                entry_price_source=src,
                result=str(result),
                side=side,
                role="maker",
                contracts=1,
                spot_at_entry=None,  # not on position row; never invent from p_fair
                spot_at_settle=spot_at_settle,
                phase="1",
                extra={
                    "experiment_id": "btc-phase1-strategy",
                    "p_fair_at_entry": row.get("p_fair"),
                    "net_ev_at_entry": row.get("net_ev"),
                    "close_time": close_time,
                    "tte_days": tte,
                    "tte_bucket": tte_b,
                    "paper": True,
                },
            )
            n_new += 1
            if n_new % 200 == 0:
                log.info("settled %d so far…", n_new)

    finally:
        await client.client.aclose()

    # Flatten tte fields onto settlement rows for scoreboard (rewrite not needed if we
    # enrich at score time from extra — scoreboard reads extra.tte_days).
    out = {
        "settlements_before": settlement_count(SETTLEMENTS) - (0 if dry_run else n_new),
        "open_considered": len(open_entries),
        "new": n_new,
        "still_pending_result": n_pending,
        "skipped": n_skip,
        "settlements_after": settlement_count(SETTLEMENTS),
        "dry_run": dry_run,
        "spot_at_settle": spot_at_settle,
    }
    print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Settle Phase-1 paper positions (no orders)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="max open entries to process")
    args = ap.parse_args()
    return asyncio.run(main_async(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
