"""Forbid scoring trades against the model's own price (the 97% artifact path)."""

from __future__ import annotations

from typing import Any, Optional


# Strings that indicate a forbidden self-score / synthetic entry path
FORBIDDEN_SOURCE_MARKERS = (
    "model_own_price",
    "model_prob_as_entry",
    "mp - threshold",
    "mp-threshold",
    "hardcoded_75",
    "hardcoded_0.75",
    "synthetic_entry",
    "self_score",
    "bucket_actual_yes_rate_as_market",
)


def is_forbidden_self_score_path(
    *,
    entry_price_source: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
) -> bool:
    """Return True if this record looks like the old analyze_calibration trap."""
    blob_parts = [str(entry_price_source or "")]
    if meta:
        blob_parts.append(json_safe(meta))
    blob = " ".join(blob_parts).lower()
    return any(m.lower() in blob for m in FORBIDDEN_SOURCE_MARKERS)


def json_safe(obj: Any) -> str:
    try:
        import json

        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def assert_entry_price_is_external(
    *,
    entry_price: float,
    entry_price_source: str,
    spot_usd: Optional[float] = None,
    kalshi_bid: Optional[float] = None,
    kalshi_ask: Optional[float] = None,
) -> None:
    """Raise if entry is not tied to an external book or admitted paper fill source.

    Allowed sources (prefix):
      - kalshi_yes_ask / kalshi_yes_bid / kalshi_no_ask / kalshi_no_bid
      - paper_limit_resting (must still store intended limit from book)
      - captured_trade
    Forbidden: anything matching FORBIDDEN_SOURCE_MARKERS.
    """
    if entry_price is None or not (0 < float(entry_price) <= 1.0 or 0 < float(entry_price) <= 100):
        # allow 0-1 or cents
        if not (0 < float(entry_price) <= 100):
            raise ValueError(f"invalid entry_price {entry_price}")

    if is_forbidden_self_score_path(entry_price_source=entry_price_source):
        raise ValueError(
            f"forbidden self-score entry_price_source={entry_price_source!r} "
            "(must use real Kalshi bid/ask, not model-own price)"
        )

    allowed_prefixes = (
        "kalshi_",
        "paper_limit",
        "captured_trade",
        "book_",
    )
    src = (entry_price_source or "").lower()
    if not any(src.startswith(p) for p in allowed_prefixes):
        raise ValueError(
            f"entry_price_source must be external book/trade, got {entry_price_source!r}"
        )

    # If book quotes provided, entry must match one of them within 1 cent
    book_prices = [p for p in (kalshi_bid, kalshi_ask) if p is not None]
    if book_prices:
        ep = float(entry_price)
        if ep > 1.0:
            ep = ep / 100.0
        normalized_book = []
        for p in book_prices:
            pf = float(p)
            normalized_book.append(pf / 100.0 if pf > 1.0 else pf)
        if not any(abs(ep - b) <= 0.011 for b in normalized_book):
            raise ValueError(
                f"entry_price {ep} not within 1c of book {normalized_book} "
                f"(source={entry_price_source})"
            )
