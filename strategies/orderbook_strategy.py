"""
Orderbook Mispricing Strategy for Kalshi BTC 15-Minute Contracts.

Approach:
1. Fetch live BTC/USDT spot price from Binance (public endpoint, no auth).
2. Parse the strike price from the market's floor_strike field.
3. Estimate the "fair" probability that BTC will be above the strike at
   settlement using a log-normal (Black-Scholes digital option) model.
4. Extract the market's implied probability from the best orderbook bids.
5. Trade YES if fair_prob >> implied_prob (market underprices YES).
   Trade NO  if fair_prob << implied_prob (market overprices YES).

This avoids all endpoints that fail on the demo API (/trades, /candlesticks)
and uses only the orderbook data that is confirmed to work.
"""

import asyncio
import logging
import time
from math import erf, exp, log, sqrt
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (no scipy needed)."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


class OrderbookMispricingStrategy(BaseStrategy):
    """
    Trades Kalshi BTC contracts when the orderbook's implied probability
    diverges meaningfully from a fair-value log-normal estimate.
    """

    # Annualized BTC volatility assumption (~80% is a reasonable long-run estimate)
    BTC_ANNUAL_VOL: float = 0.80

    # Coinbase public spot price – no API key required, no geo restrictions
    BTC_PRICE_URL: str = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    BTC_CACHE_TTL: float = 30.0  # seconds

    def __init__(self, name: str = "orderbook", settings: Optional[Dict[str, Any]] = None):
        if settings is None:
            settings = {}
        settings.setdefault("kelly_fraction", 0.25)
        settings.setdefault("max_position_size", 10.0)
        settings.setdefault("min_edge", 0.05)          # 5 cents / 5% minimum edge
        settings.setdefault("min_depth", 3)             # min contracts on best 3 levels
        settings.setdefault("min_minutes_remaining", 2) # skip nearly-expired markets
        settings.setdefault("max_minutes_remaining", 20) # skip markets too far from expiry

        super().__init__(name, settings)

        self._btc_price: Optional[float] = None
        self._btc_price_ts: float = 0.0
        self._http: httpx.AsyncClient = httpx.AsyncClient(timeout=5.0)

    # ------------------------------------------------------------------
    # Public interface (called by trader.py)
    # ------------------------------------------------------------------

    async def analyze(
        self,
        ticker: str,
        market: Dict[str, Any],
        orderbook: Dict[str, Any],
        recent_trades=None,   # ignored – not available on demo API
    ) -> Optional[Signal]:
        """
        Analyze one market and return a Signal or None.

        This method is async so the trader must await it.
        """
        try:
            # 1. Parse strike
            strike = self._parse_strike(market)
            if strike is None:
                logger.debug(f"{ticker}: no floor_strike, skipping")
                return None

            # 2. Time to expiry
            minutes_remaining = self._minutes_to_expiry(market)
            if minutes_remaining is None:
                logger.debug(f"{ticker}: no close_time, skipping")
                return None
            min_rem = self.settings["min_minutes_remaining"]
            max_rem = self.settings["max_minutes_remaining"]
            if not (min_rem <= minutes_remaining <= max_rem):
                logger.debug(
                    f"{ticker}: {minutes_remaining:.1f}m remaining, "
                    f"outside window [{min_rem}, {max_rem}]"
                )
                return None

            # 3. Live BTC price
            btc_price = await self._get_btc_price()
            if btc_price is None:
                logger.warning(f"{ticker}: BTC price unavailable, skipping")
                return None

            # 4. Fair probability
            hours_remaining = minutes_remaining / 60.0
            fair_prob = self._fair_probability(btc_price, strike, hours_remaining)

            # 5. Implied probability: try orderbook first, fall back to market-level prices
            result = self._parse_orderbook(orderbook)
            if result is None:
                result = self._parse_market_prices(market)
            if result is None:
                logger.debug(f"{ticker}: no usable bid/ask prices, skipping")
                return None
            yes_bid, yes_ask, no_bid, no_ask, yes_depth, no_depth = result

            # 6. Edge calculation
            signal = self._evaluate_edge(
                ticker=ticker,
                market=market,
                fair_prob=fair_prob,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
                yes_depth=yes_depth,
                no_depth=no_depth,
                btc_price=btc_price,
                strike=strike,
                minutes_remaining=minutes_remaining,
            )
            return signal

        except Exception as e:
            logger.error(f"OrderbookStrategy error for {ticker}: {e}", exc_info=True)
            return None

    def should_exit(
        self,
        position: Dict[str, Any],
        market: Dict[str, Any],
        orderbook: Dict[str, Any],
    ) -> bool:
        """Exit if less than 2 minutes remain (let expiry handle settlement)."""
        minutes_remaining = self._minutes_to_expiry(market)
        if minutes_remaining is not None and minutes_remaining < 2:
            logger.info(
                f"Exit signal for {market.get('ticker')}: "
                f"{minutes_remaining:.1f}m remaining, letting expiry settle"
            )
            return False  # Kalshi settles automatically; no need to exit early
        return False

    def check_exit(self, position) -> Optional[dict]:
        """Compatibility shim called by trader.py."""
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_btc_price(self) -> Optional[float]:
        """Return BTC/USD spot price from Coinbase, cached for BTC_CACHE_TTL seconds."""
        now = time.monotonic()
        if self._btc_price and (now - self._btc_price_ts) < self.BTC_CACHE_TTL:
            return self._btc_price
        try:
            resp = await self._http.get(self.BTC_PRICE_URL)
            resp.raise_for_status()
            self._btc_price = float(resp.json()["data"]["amount"])
            self._btc_price_ts = now
            logger.debug(f"BTC price refreshed: ${self._btc_price:,.2f}")
            return self._btc_price
        except Exception as e:
            logger.warning(f"Coinbase price fetch failed: {e}")
            return self._btc_price  # return stale value if any

    def _parse_strike(self, market: Dict[str, Any]) -> Optional[float]:
        """Extract strike price from market data."""
        strike = market.get("floor_strike")
        if strike is not None:
            try:
                return float(strike)
            except (TypeError, ValueError):
                pass
        # Fallback: try cap_strike for above-markets
        cap = market.get("cap_strike")
        if cap is not None:
            try:
                return float(cap)
            except (TypeError, ValueError):
                pass
        return None

    def _minutes_to_expiry(self, market: Dict[str, Any]) -> Optional[float]:
        """Return minutes until market close_time, or None if unavailable."""
        close_time_str = market.get("close_time")
        if not close_time_str:
            return None
        try:
            # Kalshi returns ISO 8601 with or without timezone info
            close_time_str = close_time_str.rstrip("Z")
            close_dt = datetime.fromisoformat(close_time_str).replace(
                tzinfo=timezone.utc
            )
            now_utc = datetime.now(timezone.utc)
            delta = (close_dt - now_utc).total_seconds() / 60.0
            return delta
        except Exception as e:
            logger.debug(f"Could not parse close_time '{close_time_str}': {e}")
            return None

    def _fair_probability(
        self, btc_price: float, strike: float, hours_remaining: float
    ) -> float:
        """
        P(BTC_spot > strike at expiry) using log-normal model.

        d = ln(S/K) / (sigma * sqrt(T))
        P(S_T > K) = N(d)  [risk-neutral, ignoring drift for short windows]
        """
        if hours_remaining <= 0:
            return 1.0 if btc_price > strike else 0.0

        T_years = hours_remaining / 8760.0
        sigma_T = self.BTC_ANNUAL_VOL * sqrt(T_years)
        if sigma_T < 1e-9:
            return 1.0 if btc_price > strike else 0.0

        d = log(btc_price / strike) / sigma_T
        prob = _norm_cdf(d)
        # Clamp to avoid extreme probs from very deep in/out-of-money contracts
        return max(0.02, min(0.98, prob))

    def _parse_market_prices(
        self, market: Dict[str, Any]
    ) -> Optional[Tuple[float, float, float, float, int, int]]:
        """
        Extract bid/ask from market-level fields (yes_bid_dollars, yes_ask_dollars, etc.).
        Used as fallback when the orderbook endpoint returns empty data.

        Returns same tuple as _parse_orderbook, with depth=999 (unknown but assumed liquid).
        """
        yes_bid = market.get("yes_bid_dollars")
        yes_ask = market.get("yes_ask_dollars")
        no_bid = market.get("no_bid_dollars")
        no_ask = market.get("no_ask_dollars")

        # Need at least one side
        if yes_ask is None and no_ask is None:
            return None

        try:
            yes_bid = float(yes_bid) if yes_bid is not None else None
            yes_ask = float(yes_ask) if yes_ask is not None else None
            no_bid = float(no_bid) if no_bid is not None else None
            no_ask = float(no_ask) if no_ask is not None else None
        except (TypeError, ValueError):
            return None

        # Derive missing values from complements
        if yes_ask is None and no_bid is not None:
            yes_ask = 1.0 - no_bid
        if no_ask is None and yes_bid is not None:
            no_ask = 1.0 - yes_bid
        if yes_bid is None and no_ask is not None:
            yes_bid = 1.0 - no_ask
        if no_bid is None and yes_ask is not None:
            no_bid = 1.0 - yes_ask

        if yes_ask is None and no_ask is None:
            return None

        # Sanity checks
        if yes_ask is not None and not (0 < yes_ask < 1):
            return None
        if no_ask is not None and not (0 < no_ask < 1):
            return None

        # depth=999 signals we used market-level prices (liquidity assumed present)
        return yes_bid, yes_ask, no_bid, no_ask, 999, 999

    def _parse_orderbook(
        self, orderbook: Dict[str, Any]
    ) -> Optional[Tuple[float, float, float, float, int, int]]:
        """
        Parse orderbook into (yes_bid, yes_ask, no_bid, no_ask, yes_depth, no_depth).

        Kalshi orderbook format:
            {"orderbook": {"yes": [[price_cents, qty], ...], "no": [[price_cents, qty], ...]}}

        Prices are integers in cents (1–99).
        YES levels are bids to buy YES; NO levels are bids to buy NO.

        Returns None if the orderbook is too thin to trade.
        """
        ob = orderbook.get("orderbook", orderbook)
        if not isinstance(ob, dict):
            return None

        yes_levels = ob.get("yes", [])
        no_levels = ob.get("no", [])

        if not yes_levels and not no_levels:
            return None

        # Sort descending by price (best bid first)
        yes_sorted = sorted(yes_levels, key=lambda x: x[0], reverse=True)
        no_sorted = sorted(no_levels, key=lambda x: x[0], reverse=True)

        # Best bids (prices people will pay, in 0-1 scale)
        best_yes_bid = yes_sorted[0][0] / 100.0 if yes_sorted else None
        best_no_bid = no_sorted[0][0] / 100.0 if no_sorted else None

        # To buy YES you take the other side of the best NO bid
        # YES ask = 1 - best_no_bid
        # To buy NO you take the other side of the best YES bid
        # NO ask = 1 - best_yes_bid
        yes_ask = (1.0 - best_no_bid) if best_no_bid is not None else None
        no_ask = (1.0 - best_yes_bid) if best_yes_bid is not None else None

        # Use bid if ask is unavailable (thin book) for implied probability
        if yes_ask is None and best_yes_bid is not None:
            yes_ask = best_yes_bid + 0.01  # rough ask estimate

        if no_ask is None and best_no_bid is not None:
            no_ask = best_no_bid + 0.01

        if yes_ask is None and no_ask is None:
            return None

        # Mid-price as implied probability
        yes_bid = best_yes_bid if best_yes_bid is not None else (1.0 - no_ask if no_ask else 0.5)
        no_bid = best_no_bid if best_no_bid is not None else (1.0 - yes_ask if yes_ask else 0.5)

        # Depth: total contracts available on top 3 levels
        yes_depth = sum(lvl[1] for lvl in yes_sorted[:3]) if yes_sorted else 0
        no_depth = sum(lvl[1] for lvl in no_sorted[:3]) if no_sorted else 0

        # Require minimum depth for at least one side
        min_depth = self.settings["min_depth"]
        if yes_depth < min_depth and no_depth < min_depth:
            logger.debug(
                f"Orderbook too thin: yes_depth={yes_depth}, no_depth={no_depth}"
            )
            return None

        return yes_bid, yes_ask, no_bid, no_ask, yes_depth, no_depth

    def _evaluate_edge(
        self,
        ticker: str,
        market: Dict[str, Any],
        fair_prob: float,
        yes_bid: Optional[float],
        yes_ask: Optional[float],
        no_bid: Optional[float],
        no_ask: Optional[float],
        yes_depth: int,
        no_depth: int,
        btc_price: float,
        strike: float,
        minutes_remaining: float,
    ) -> Optional[Signal]:
        """
        Compare fair_prob to implied prices and return a Signal if edge >= min_edge.
        """
        min_edge = self.settings["min_edge"]
        bankroll = market.get("bankroll", 1000.0)

        # depth=999 means market-level prices (skip depth check)
        min_depth = self.settings["min_depth"]

        # --- Try YES trade ---
        if yes_ask is not None and 0 < yes_ask < 1 and (yes_depth >= min_depth or yes_depth == 999):
            ev_yes = fair_prob - yes_ask  # EV per dollar risked
            if ev_yes >= min_edge:
                kelly = self.calculate_kelly(fair_prob, yes_ask)
                size = self.calculate_position_size(kelly, bankroll)
                reasoning = (
                    f"BUY YES | BTC ${btc_price:,.0f} vs strike ${strike:,.0f} | "
                    f"fair={fair_prob:.3f} ask={yes_ask:.3f} EV={ev_yes:+.3f} | "
                    f"{minutes_remaining:.1f}m remaining"
                )
                logger.info(f"{ticker}: {reasoning}")
                return Signal(
                    direction="BUY",
                    strategy_name=self.name,
                    model_probability=fair_prob,
                    confidence=min(ev_yes * 4, 1.0),
                    position_size_usd=size,
                    entry_price=yes_ask,
                    reasoning=reasoning,
                    metadata={
                        "side": "yes",
                        "ticker": ticker,
                        "yes_ask": yes_ask,
                        "no_bid": no_bid,
                        "fair_prob": fair_prob,
                        "ev": ev_yes,
                        "btc_price": btc_price,
                        "strike": strike,
                        "minutes_remaining": minutes_remaining,
                    },
                )

        # --- Try NO trade ---
        if no_ask is not None and 0 < no_ask < 1 and (no_depth >= min_depth or no_depth == 999):
            fair_no_prob = 1.0 - fair_prob
            ev_no = fair_no_prob - no_ask
            if ev_no >= min_edge:
                kelly = self.calculate_kelly(fair_no_prob, no_ask)
                size = self.calculate_position_size(kelly, bankroll)
                reasoning = (
                    f"BUY NO | BTC ${btc_price:,.0f} vs strike ${strike:,.0f} | "
                    f"fair_no={fair_no_prob:.3f} no_ask={no_ask:.3f} EV={ev_no:+.3f} | "
                    f"{minutes_remaining:.1f}m remaining"
                )
                logger.info(f"{ticker}: {reasoning}")
                return Signal(
                    direction="SELL",  # SELL = buy NO in our schema
                    strategy_name=self.name,
                    model_probability=fair_no_prob,
                    confidence=min(ev_no * 4, 1.0),
                    position_size_usd=size,
                    entry_price=no_ask,
                    reasoning=reasoning,
                    metadata={
                        "side": "no",
                        "ticker": ticker,
                        "no_ask": no_ask,
                        "yes_bid": yes_bid,
                        "fair_prob": fair_prob,
                        "ev": ev_no,
                        "btc_price": btc_price,
                        "strike": strike,
                        "minutes_remaining": minutes_remaining,
                    },
                )

        logger.debug(
            f"{ticker}: no edge | fair={fair_prob:.3f} "
            f"yes_ask={yes_ask} no_ask={no_ask} "
            f"BTC=${btc_price:,.0f} K=${strike:,.0f} {minutes_remaining:.1f}m"
        )
        return None
