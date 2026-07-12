#!/usr/bin/env python3
"""Phase 0 capture runner — independent spot + Kalshi books. NEVER places orders.

Usage (from bot root):
  python deploy/run_phase0_capture.py --once
  python deploy/run_phase0_capture.py --loops 10 --interval 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from data.kalshi_client import KalshiClient
from measurement.capture import run_capture_cycle
from measurement.settlement import settlement_count
from measurement.spot import fetch_btc_spot_usd
from measurement.store import count_lines
from snapshot_emit import build_btc_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("phase0")


def _update_snapshot_phase0(settings, summary: dict) -> None:
    """Honest snapshot: phase0 capturing, still no alpha claim."""
    try:
        from datetime import datetime, timezone
        from umbrella_core.emit import snapshot_to_dict, write_snapshot_atomic
        from umbrella_core.snapshot import validate_snapshot

        snap = build_btc_snapshot(settings, killed=False)
        # rebuild with phase0 messaging via health warnings
        d = snapshot_to_dict(snap)
        d["lifecycle"]["stage"] = "paper-validating"
        d["lifecycle"]["mode"] = "paper"
        d["lifecycle"]["killed"] = False
        # Paper sleeve $100 — intended live fund size for honest fleet display
        sleeve = 100.0
        d["capital"] = {
            "base_currency": "USD",
            "own_nav": sleeve,
            "cash": sleeve,
            "invested": 0.0,
            "budget_allocation": sleeve,
            "day_pnl": None,
            "total_pnl": None,
        }
        d["health"]["overall"] = "ok" if summary.get("spot_ok") else "degraded"
        d["health"]["warnings"] = [
            "PHASE0 measurement capture running — no strategy edge claims",
            f"captures_ok={summary.get('measurement_ok_count')} decisions={summary.get('decisions_emitted')}",
            "97% backtest artifact is NOT evidence — ignored",
        ]
        d["timing"]["last_cycle_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        d["extra"] = {
            "phase": "0",
            "measurement_artifact": False,
            "paper_sleeve_usd": sleeve,
            "phase0_summary": summary,
        }
        errs = validate_snapshot(d)
        if errs:
            log.warning("snapshot invalid: %s", errs[:3])
            return
        out = ROOT / "data" / "state.json"
        write_snapshot_atomic(out, d)
        log.info("wrote snapshot %s", out)
    except Exception as exc:
        log.warning("snapshot update failed: %s", exc)


async def _once(settings, args) -> dict:
    client = KalshiClient(
        api_key_id=settings.KALSHI_API_KEY_ID,
        private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
        base_url=settings.base_url,
        paper_trade=True,  # belt-and-suspenders: never live orders from this client
    )
    try:
        summary = await run_capture_cycle(
            client,
            settings,
            max_markets=args.max_markets,
            emit_decisions=not args.no_decisions,
        )
        summary["settlements_n"] = settlement_count(ROOT / "data" / "settlements.jsonl")
        summary["captures_total"] = count_lines(ROOT / "data" / "captures.jsonl")
        _update_snapshot_phase0(settings, summary)
        return summary
    finally:
        await client.client.aclose()


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 0 BTC measurement capture (no orders)")
    ap.add_argument("--once", action="store_true", help="Single cycle")
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--interval", type=int, default=120, help="Seconds between loops")
    ap.add_argument("--max-markets", type=int, default=15)
    ap.add_argument("--no-decisions", action="store_true")
    ap.add_argument("--spot-only", action="store_true", help="Test independent spot only")
    args = ap.parse_args()

    if args.spot_only:
        q = fetch_btc_spot_usd()
        print(json.dumps({
            "ok": q.ok,
            "price_usd": q.price_usd,
            "source": q.source,
            "error": q.error,
            "latency_ms": q.latency_ms,
        }, indent=2))
        return 0 if q.ok else 1

    settings = get_settings()
    log.info(
        "Phase 0 capture start env=%s paper_client=True loops=%s",
        settings.KALSHI_ENV,
        1 if args.once else args.loops,
    )

    loops = 1 if args.once else max(1, args.loops)
    last = {}
    for i in range(loops):
        last = asyncio.run(_once(settings, args))
        print(json.dumps(last, indent=2))
        if i + 1 < loops:
            time.sleep(args.interval)
    return 0 if last.get("spot_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
