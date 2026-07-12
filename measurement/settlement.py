"""Settlement recorder — marks paper captures against market result + independent spot.

Does not place orders. Reads captures / open paper intents and writes settlements.jsonl.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .fees import fee_for_role
from .self_score_guard import assert_entry_price_is_external
from .store import append_jsonl, read_jsonl


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def realized_pnl_yes(
    *,
    entry_price: float,
    result: str,
    role: str = "taker",
    contracts: int = 1,
) -> dict[str, float]:
    """result: 'yes' | 'no'. Entry is YES buy price in [0,1]."""
    p = float(entry_price)
    if p > 1:
        p = p / 100.0
    fee = fee_for_role(p, "taker" if role == "taker" else "maker", contracts=contracts)
    if result == "yes":
        gross = (1.0 - p) * contracts
    elif result == "no":
        gross = (-p) * contracts
    else:
        raise ValueError(f"unknown result {result}")
    return {
        "gross_pnl": round(gross, 6),
        "fees": round(fee, 6),
        "net_pnl": round(gross - fee, 6),
    }


def record_settlement(
    path: str | Path,
    *,
    ticker: str,
    decision_id: str,
    entry_price: float,
    entry_price_source: str,
    result: str,
    side: str = "yes",
    role: str = "taker",
    contracts: int = 1,
    spot_at_entry: Optional[float] = None,
    spot_at_settle: Optional[float] = None,
    kalshi_bid: Optional[float] = None,
    kalshi_ask: Optional[float] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one settlement row after external price assertion."""
    assert_entry_price_is_external(
        entry_price=entry_price,
        entry_price_source=entry_price_source,
        kalshi_bid=kalshi_bid,
        kalshi_ask=kalshi_ask,
    )
    if side == "yes":
        pnl = realized_pnl_yes(
            entry_price=entry_price, result=result, role=role, contracts=contracts
        )
    else:
        # NO buy: win when result==no
        p = float(entry_price)
        if p > 1:
            p = p / 100.0
        fee = fee_for_role(p, "taker" if role == "taker" else "maker", contracts=contracts)
        if result == "no":
            gross = (1.0 - p) * contracts
        else:
            gross = (-p) * contracts
        pnl = {
            "gross_pnl": round(gross, 6),
            "fees": round(fee, 6),
            "net_pnl": round(gross - fee, 6),
        }

    row = {
        "ts": _iso_now(),
        "ticker": ticker,
        "decision_id": decision_id,
        "side": side,
        "role": role,
        "contracts": contracts,
        "entry_price": entry_price,
        "entry_price_source": entry_price_source,
        "result": result,
        "spot_at_entry": spot_at_entry,
        "spot_at_settle": spot_at_settle,
        **pnl,
        "phase": "0",
    }
    if extra:
        row["extra"] = extra
    append_jsonl(path, row)
    return row


def settlement_count(path: str | Path) -> int:
    return len(read_jsonl(path))
