"""Normalize Kalshi orderbook payloads to bid/ask in [0,1] probability dollars."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


def _to_prob(price: Any) -> Optional[float]:
    if price is None:
        return None
    p = float(price)
    if p > 1.0:  # cents
        p = p / 100.0
    if not 0 <= p <= 1:
        return None
    return p


def _best_from_levels(levels: Any, *, highest: bool) -> Optional[float]:
    """levels may be [[price, size], ...] or [{price, size}, ...]."""
    if not levels:
        return None
    prices: list[float] = []
    for lv in levels:
        if isinstance(lv, (list, tuple)) and len(lv) >= 1:
            pp = _to_prob(lv[0])
        elif isinstance(lv, dict):
            pp = _to_prob(lv.get("price", lv.get("yes_price")))
        else:
            continue
        if pp is not None:
            prices.append(pp)
    if not prices:
        return None
    return max(prices) if highest else min(prices)


@dataclass
class BookSnap:
    ticker: str
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]
    raw_keys: list[str]

    @property
    def yes_mid(self) -> Optional[float]:
        if self.yes_bid is not None and self.yes_ask is not None:
            return round((self.yes_bid + self.yes_ask) / 2.0, 4)
        return None

    def tradeable_yes_buy(self) -> Optional[float]:
        """Price to lift the ask (taker buy YES)."""
        return self.yes_ask

    def tradeable_no_buy(self) -> Optional[float]:
        return self.no_ask


def parse_orderbook(ticker: str, payload: dict[str, Any]) -> BookSnap:
    """Parse various Kalshi orderbook shapes into BookSnap."""
    # Unwrap common envelopes
    ob = payload.get("orderbook") or payload.get("orderbook_fp") or payload
    yes_bids = ob.get("yes") or ob.get("yes_dollars") or ob.get("yes_bids") or []
    # Kalshi often returns only yes side; no is complement of yes book
    no_bids = ob.get("no") or ob.get("no_dollars") or ob.get("no_bids") or []

    # Some APIs: yes = bids descending; asks derived differently
    # Newer API: orderbook.yes is bid levels; yes asks = 1 - no bids
    yes_bid = _best_from_levels(yes_bids, highest=True)
    no_bid = _best_from_levels(no_bids, highest=True)

    # If only yes bids present: yes_ask ≈ 1 - no_bid when no side exists
    yes_ask = _best_from_levels(
        ob.get("yes_asks") or ob.get("yes_ask") or [],
        highest=False,
    )
    no_ask = _best_from_levels(
        ob.get("no_asks") or ob.get("no_ask") or [],
        highest=False,
    )

    # Complement reconstruction (common on Kalshi)
    if yes_ask is None and no_bid is not None:
        yes_ask = round(1.0 - no_bid, 4)
    if no_ask is None and yes_bid is not None:
        no_ask = round(1.0 - yes_bid, 4)
    if no_bid is None and yes_ask is not None:
        no_bid = round(1.0 - yes_ask, 4)
    if yes_bid is None and no_ask is not None:
        yes_bid = round(1.0 - no_ask, 4)

    # Market object may only have yes_bid / yes_ask fields
    if yes_bid is None:
        yes_bid = _to_prob(ob.get("yes_bid") or payload.get("yes_bid"))
    if yes_ask is None:
        yes_ask = _to_prob(ob.get("yes_ask") or payload.get("yes_ask"))

    return BookSnap(
        ticker=ticker,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        raw_keys=sorted(str(k) for k in (ob.keys() if isinstance(ob, dict) else [])),
    )


def market_top_of_book_from_market_dict(ticker: str, m: dict[str, Any]) -> BookSnap:
    """Fallback when orderbook endpoint fails: use market yes_bid/yes_ask fields."""
    # API may use yes_bid_dollars / yes_ask_dollars or integer cents
    yb = m.get("yes_bid_dollars") or m.get("yes_bid")
    ya = m.get("yes_ask_dollars") or m.get("yes_ask")
    # last price fallbacks — NOT used as bid/ask for trading; only mark if both missing
    return BookSnap(
        ticker=ticker,
        yes_bid=_to_prob(yb),
        yes_ask=_to_prob(ya),
        no_bid=_to_prob(m.get("no_bid_dollars") or m.get("no_bid")),
        no_ask=_to_prob(m.get("no_ask_dollars") or m.get("no_ask")),
        raw_keys=sorted(m.keys()),
    )
