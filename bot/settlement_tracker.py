"""
Settlement Tracker for paper trades.

After a contract expires, queries Kalshi API for the settlement result (yes/no)
and calculates realized P&L. Persists results to logs/settlements.json so the
dashboard can display them without needing a live bot connection.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SETTLEMENTS_PATH = Path(__file__).parent.parent / "logs" / "settlements.json"

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_expiry_utc(ticker: str) -> Optional[datetime]:
    """Parse UTC expiry datetime from ticker like KXBTC15M-26APR082145-45."""
    import re
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})-", ticker)
    if not m:
        return None
    day, mon, yr, hh, mm = m.groups()
    try:
        return datetime(2000 + int(yr), MONTHS[mon], int(day), int(hh), int(mm),
                        tzinfo=timezone.utc)
    except Exception:
        return None


def load_settlements() -> dict:
    """Load existing settlement records from disk."""
    if SETTLEMENTS_PATH.exists():
        try:
            return json.loads(SETTLEMENTS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_settlements(settlements: dict) -> None:
    """Persist settlement records to disk."""
    SETTLEMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTLEMENTS_PATH.write_text(json.dumps(settlements, indent=2))


def calculate_pnl(side: str, price: float, count: int, result: str) -> float:
    """
    Calculate realized P&L for a settled contract.

    Kalshi contracts pay $1.00 per contract to the winning side.

    Args:
        side:   "BUY"  = bought YES contracts
                "SELL" = bought NO contracts
        price:  price paid per contract (0-1 scale)
        count:  number of contracts
        result: "yes" or "no" (settlement outcome)

    Returns:
        Realized P&L in dollars
    """
    result = result.lower()
    if side.upper() == "BUY":
        # Bought YES at `price`. Win $1 if YES, lose stake if NO.
        won = (result == "yes")
    else:
        # Bought NO at `price`. Win $1 if NO, lose stake if YES.
        won = (result == "no")

    if won:
        return (1.0 - price) * count
    else:
        return -price * count


async def check_and_record(kalshi_client, paper_trades: list) -> dict:
    """
    For each expired paper trade not yet settled, query Kalshi and record the result.

    Args:
        kalshi_client: authenticated KalshiClient instance
        paper_trades:  list of EXECUTION dicts from the log

    Returns:
        Updated settlements dict (ticker -> settlement record)
    """
    settlements = load_settlements()
    now_utc = datetime.now(timezone.utc)

    # Deduplicate tickers that need checking
    checked_tickers = set(settlements.keys())
    tickers_to_check = set()
    for trade in paper_trades:
        ticker = trade.get("ticker", "")
        if ticker and ticker not in checked_tickers:
            expiry = parse_expiry_utc(ticker)
            if expiry and expiry < now_utc:
                tickers_to_check.add(ticker)

    for ticker in tickers_to_check:
        try:
            resp = await kalshi_client.get_market(ticker)
            market = resp.get("market", resp)  # API wraps in {"market": {...}}
            result = market.get("result", "")
            status = market.get("status", "")

            if result in ("yes", "no"):
                # Gather all trades on this ticker
                ticker_trades = [t for t in paper_trades if t.get("ticker") == ticker]
                total_pnl = sum(
                    calculate_pnl(t["side"], t["price"], t["count"], result)
                    for t in ticker_trades
                )
                expiry = parse_expiry_utc(ticker)
                settlements[ticker] = {
                    "ticker": ticker,
                    "result": result,
                    "settled_at": expiry.isoformat() if expiry else "",
                    "total_pnl": round(total_pnl, 4),
                    "trades": len(ticker_trades),
                    "checked_at": now_utc.isoformat(),
                }
                logger.info(
                    f"Settlement: {ticker} → {result.upper()} | "
                    f"P&L: ${total_pnl:+.2f} ({len(ticker_trades)} orders)"
                )
            elif status in ("finalized", "closed"):
                # Settled but result field missing — mark as unknown
                settlements[ticker] = {
                    "ticker": ticker,
                    "result": "unknown",
                    "settled_at": "",
                    "total_pnl": 0,
                    "trades": 0,
                    "checked_at": now_utc.isoformat(),
                }
        except Exception as e:
            logger.debug(f"Could not fetch settlement for {ticker}: {e}")

    if tickers_to_check:
        save_settlements(settlements)

    return settlements
