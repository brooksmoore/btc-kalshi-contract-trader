"""
Historical data ingestion for KXBTC15M calibration.

For each settled contract, fetches:
  - Strike price, close_time, result (yes/no)  [from Kalshi]
  - BTC spot price at T-2, T-5, T-10, T-15 min before expiry [from Coinbase Exchange]

Then computes what the model's fair_prob would have been at each checkpoint,
so we can measure calibration: "when model says P%, does YES resolve P% of the time?"

Output: data/history.json  (list of contract records)

Usage:
    python3.11 deploy/fetch_history.py --days 60
    python3.11 deploy/fetch_history.py --days 30 --out data/history_30d.json
"""

import asyncio
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from math import erf, exp, log, sqrt
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data.kalshi_client import KalshiClient
from config.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ── constants ──────────────────────────────────────────────────────────────────

BTC_ANNUAL_VOL = 0.80          # same as orderbook_strategy
CHECKPOINTS_MIN = [2, 5, 10, 15]  # minutes before expiry to sample
KALSHI_PAGE_SIZE = 200
KALSHI_RATE_LIMIT_SLEEP = 1.2  # seconds between pages to avoid 429

# ── probability model (copy of orderbook_strategy logic) ──────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def fair_probability(btc_price: float, strike: float, hours_remaining: float) -> float:
    if hours_remaining <= 0:
        return 1.0 if btc_price > strike else 0.0
    T_years = hours_remaining / 8760.0
    sigma_T = BTC_ANNUAL_VOL * sqrt(T_years)
    if sigma_T < 1e-9:
        return 1.0 if btc_price > strike else 0.0
    d = log(btc_price / strike) / sigma_T
    return max(0.02, min(0.98, _norm_cdf(d)))


# ── Coinbase 1-minute candle fetcher ──────────────────────────────────────────

async def btc_price_at(http: httpx.AsyncClient, ts: datetime) -> float | None:
    """Return the BTC close price of the 1-minute candle containing `ts`."""
    candle_start = ts.replace(second=0, microsecond=0)
    candle_end   = candle_start + timedelta(minutes=2)
    try:
        resp = await http.get(
            "https://api.exchange.coinbase.com/products/BTC-USD/candles",
            params={
                "granularity": 60,
                "start": candle_start.isoformat(),
                "end":   candle_end.isoformat(),
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        candles = resp.json()
        if isinstance(candles, list) and candles:
            # Coinbase returns [time, low, high, open, close, volume]
            # Find candle whose timestamp matches
            for c in candles:
                c_ts = datetime.fromtimestamp(c[0], tz=timezone.utc)
                if abs((c_ts - candle_start).total_seconds()) <= 60:
                    return float(c[4])  # close price
            return float(candles[0][4])
    except Exception as e:
        logger.debug("Coinbase price fetch failed for %s: %s", ts.isoformat(), e)
    return None


# ── Kalshi settled market fetcher ─────────────────────────────────────────────

async def fetch_settled_markets(client: KalshiClient, days: int) -> list[dict]:
    """
    Fetch all settled KXBTC15M markets going back `days` days.
    Returns list of raw market dicts from Kalshi API.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    markets = []
    cursor = None
    page = 0

    while True:
        params = {
            "series_ticker": "KXBTC15M",
            "status": "settled",
            "limit": KALSHI_PAGE_SIZE,
        }
        if cursor:
            params["cursor"] = cursor

        try:
            resp = await client._request("GET", "/markets", params=params)
        except Exception as e:
            logger.error("Kalshi API error on page %d: %s", page + 1, e)
            break

        page_markets = resp.get("markets", []) if isinstance(resp, dict) else []
        if not page_markets:
            break

        page += 1
        cursor = resp.get("cursor") if isinstance(resp, dict) else None

        # Filter to within date range
        in_range = []
        oldest_on_page = None
        for m in page_markets:
            close_str = m.get("close_time", "")
            if not close_str:
                continue
            try:
                close_dt = datetime.fromisoformat(close_str.rstrip("Z")).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if oldest_on_page is None or close_dt < oldest_on_page:
                oldest_on_page = close_dt
            if close_dt >= cutoff:
                in_range.append(m)

        markets.extend(in_range)
        logger.info(
            "Page %d: %d markets in range (oldest on page: %s, total so far: %d)",
            page,
            len(in_range),
            oldest_on_page.strftime("%Y-%m-%d") if oldest_on_page else "?",
            len(markets),
        )

        # Stop if we've gone past the cutoff
        if oldest_on_page and oldest_on_page < cutoff:
            logger.info("Reached cutoff date, stopping pagination.")
            break

        if not cursor:
            break

        await asyncio.sleep(KALSHI_RATE_LIMIT_SLEEP)

    return markets


# ── main ingestion ─────────────────────────────────────────────────────────────

async def ingest(days: int, out_path: Path) -> None:
    s = Settings()
    client = KalshiClient(
        api_key_id=s.KALSHI_API_KEY_ID,
        private_key_path=s.KALSHI_PRIVATE_KEY_PATH,
        base_url=s.base_url,
    )

    logger.info("Fetching settled KXBTC15M markets for past %d days...", days)
    raw_markets = await fetch_settled_markets(client, days)
    await client.close()

    logger.info("Fetched %d settled contracts. Fetching BTC prices...", len(raw_markets))

    records = []
    async with httpx.AsyncClient() as http:
        for i, m in enumerate(raw_markets):
            ticker      = m.get("ticker", "")
            result      = m.get("result", "")
            strike      = m.get("floor_strike")
            close_str   = m.get("close_time", "")

            if result not in ("yes", "no") or not strike or not close_str:
                continue

            try:
                strike = float(strike)
                close_dt = datetime.fromisoformat(close_str.rstrip("Z")).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            record = {
                "ticker":     ticker,
                "result":     result,
                "strike":     strike,
                "close_time": close_dt.isoformat(),
                "checkpoints": [],
            }

            # For each checkpoint, fetch BTC price and compute model prob
            for mins in CHECKPOINTS_MIN:
                sample_ts = close_dt - timedelta(minutes=mins)
                btc = await btc_price_at(http, sample_ts)
                if btc is None:
                    continue
                hours_rem = mins / 60.0
                prob = fair_probability(btc, strike, hours_rem)
                record["checkpoints"].append({
                    "mins_before_expiry": mins,
                    "btc_price":          round(btc, 2),
                    "model_prob":         round(prob, 4),
                    "btc_vs_strike_pct":  round((btc - strike) / strike * 100, 4),
                })

            records.append(record)

            if (i + 1) % 50 == 0:
                logger.info("  Processed %d / %d contracts...", i + 1, len(raw_markets))

            # Light rate limiting for Coinbase
            await asyncio.sleep(0.05)

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2))
    logger.info("Saved %d records to %s", len(records), out_path)

    # Quick summary
    yes_count = sum(1 for r in records if r["result"] == "yes")
    no_count  = sum(1 for r in records if r["result"] == "no")
    logger.info("Result breakdown: YES=%d (%.1f%%)  NO=%d (%.1f%%)",
                yes_count, 100 * yes_count / len(records) if records else 0,
                no_count,  100 * no_count  / len(records) if records else 0)


def main():
    parser = argparse.ArgumentParser(description="Fetch KXBTC15M historical data for calibration")
    parser.add_argument("--days", type=int, default=60, help="Days of history to fetch (default: 60)")
    parser.add_argument("--out", type=str, default="data/history.json", help="Output file path")
    args = parser.parse_args()

    out_path = PROJECT_ROOT / args.out
    asyncio.run(ingest(args.days, out_path))


if __name__ == "__main__":
    main()
