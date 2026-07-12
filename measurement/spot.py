"""Independent BTC/USD spot — never from the bot's fair-value model."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional


@dataclass(frozen=True)
class SpotQuote:
    symbol: str
    price_usd: float
    source: str
    ts: str  # ISO8601 UTC
    latency_ms: float
    ok: bool
    error: Optional[str] = None

    def age_sec(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        ts = datetime.fromisoformat(self.ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (now - ts).total_seconds())


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_btc_spot_coinbase(
    *,
    timeout_sec: float = 10.0,
    urlopen: Callable = urllib.request.urlopen,
) -> SpotQuote:
    """Public Coinbase spot (no API key). Fail-closed on error."""
    url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "btc-bot-phase0/1.0"})
        with urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        amount = float(payload["data"]["amount"])
        if amount <= 0:
            raise ValueError(f"non-positive spot {amount}")
        latency = (time.perf_counter() - t0) * 1000.0
        return SpotQuote(
            symbol="BTC-USD",
            price_usd=amount,
            source="coinbase_spot",
            ts=_iso_now(),
            latency_ms=round(latency, 2),
            ok=True,
        )
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        latency = (time.perf_counter() - t0) * 1000.0
        return SpotQuote(
            symbol="BTC-USD",
            price_usd=float("nan"),
            source="coinbase_spot",
            ts=_iso_now(),
            latency_ms=round(latency, 2),
            ok=False,
            error=str(exc),
        )


def fetch_btc_spot_usd(**kwargs) -> SpotQuote:
    """Primary independent spot. Extend with fallbacks later if needed."""
    return fetch_btc_spot_coinbase(**kwargs)


def is_stale(quote: SpotQuote, *, max_age_sec: float = 30.0) -> bool:
    if not quote.ok:
        return True
    return quote.age_sec() > max_age_sec
