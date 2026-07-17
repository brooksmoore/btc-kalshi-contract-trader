"""
Main Trading Coordinator for Kalshi Bitcoin Trading Bot

Orchestrates the complete trading loop:
1. Scan markets for active BTC contracts
2. Analyze each market (orderbook, trades, strategy signal)
3. Execute entry signals (risk checks, size calculation)
4. Manage open positions (monitor exit conditions)
5. Log all actions

Integrates:
- Strategy (provides signals with expected value)
- RiskManager (enforces position limits, P&L caps)
- OrderManager (order lifecycle)
- PositionTracker (position/trade history)
"""

import inspect
import logging
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import json

logger = logging.getLogger(__name__)

# Live arm confirm (token, not a credential). Phrase lives only in env values —
# never hard-code as a secret. Mirror Multi MULTI_RH_LIVE_CONFIRM pattern.
_BTC_LIVE_CONFIRM_ENV = "BTC_LIVE_CONFIRM"
_BTC_LIVE_CONFIRM_PHRASE = "ARM-REAL-MONEY"


class Trader:
    """
    Main execution coordinator for the trading bot.
    """

    def __init__(
        self,
        kalshi_client,
        strategy,
        risk_manager,
        order_manager,
        position_tracker,
        settings: dict,
        alerter=None,
        paper_trade: Optional[bool] = None,
    ):
        """
        Initialize trader.

        Args:
            kalshi_client: Kalshi API client instance
            strategy: Strategy instance with analyze(market) -> signal dict
            risk_manager: RiskManager instance
            order_manager: OrderManager instance
            position_tracker: PositionTracker instance
            settings: Configuration dict with keys:
                - TARGET_TICKERS: list of tickers to trade (e.g., ['BTCUSD_DAILY', ...])
                - MAX_POSITIONS: max concurrent positions
                - CYCLE_INTERVAL: seconds between trading cycles
                - LOG_METRICS_INTERVAL: seconds between metric logs
            paper_trade: If False, requires env BTC_LIVE_CONFIRM=ARM-REAL-MONEY.
                If None, inferred from kalshi_client.paper_trade (default False if missing).
        """
        if paper_trade is None:
            paper_trade = bool(getattr(kalshi_client, "paper_trade", False))
        if not paper_trade:
            confirm = os.environ.get(_BTC_LIVE_CONFIRM_ENV, "")
            if confirm != _BTC_LIVE_CONFIRM_PHRASE:
                raise RuntimeError(
                    "Refusing to construct Trader with paper_trade=False: btc-bot has "
                    "no pre-registered go-live gate. Set env "
                    f"{_BTC_LIVE_CONFIRM_ENV}={_BTC_LIVE_CONFIRM_PHRASE!r} only after "
                    "a written live gate is approved. Use paper_trade=True / "
                    "deploy/run_phase1.py for the supported path."
                )

        self.paper_trade = bool(paper_trade)
        self.kalshi_client = kalshi_client
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.position_tracker = position_tracker
        self.settings = settings

        self.alerter = alerter
        self.target_tickers = settings.get("TARGET_TICKERS", [])
        self.cycle_interval = settings.get("CYCLE_INTERVAL", 60)
        self.log_metrics_interval = settings.get("LOG_METRICS_INTERVAL", 300)

        # Execution state
        self.is_running = False
        self.cycle_count = 0
        self.last_metrics_log = datetime.utcnow()

        # Market cache
        self.markets: Dict[str, dict] = {}  # ticker -> market data

        logger.info(
            f"Trader initialized: paper_trade={self.paper_trade}, "
            f"target_tickers={self.target_tickers}, "
            f"cycle_interval={self.cycle_interval}s"
        )

    async def initialize(self) -> None:
        """Initialize trader and database."""
        await self.position_tracker.initialize()
        logger.info("Trader initialization complete")

    async def shutdown(self) -> None:
        """Shutdown trader and close database."""
        await self.position_tracker.close()
        await self.order_manager.cancel_all_orders()
        logger.info("Trader shutdown complete")

    async def run_cycle(self) -> None:
        """
        Execute one complete trading cycle:
        1. Scan markets
        2. Analyze each market
        3. Execute signals
        4. Manage positions
        5. Log metrics

        This is the main loop function.
        """
        self.cycle_count += 1
        cycle_start = datetime.utcnow()

        try:
            logger.info(f"=== Trading Cycle #{self.cycle_count} started ===")

            # Step 1: Scan markets
            await self.scan_markets()

            # Step 2: Analyze and execute all discovered BTC markets
            for ticker, market in list(self.markets.items()):
                await self.analyze_market(market)

            # Step 3: Manage positions
            await self.manage_positions()

            # Step 4: Periodic metrics logging
            if (datetime.utcnow() - self.last_metrics_log).total_seconds() >= self.log_metrics_interval:
                self._log_metrics()
                self.last_metrics_log = datetime.utcnow()

            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            logger.info(f"=== Trading Cycle #{self.cycle_count} completed in {cycle_duration:.2f}s ===")

        except Exception as e:
            logger.error(f"Error during trading cycle: {str(e)}", exc_info=True)

    async def run(self) -> None:
        """
        Main bot loop. Runs indefinitely until stopped.
        """
        self.is_running = True
        logger.info("Bot starting main loop")

        try:
            while self.is_running:
                await self.run_cycle()
                await asyncio.sleep(self.cycle_interval)
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in bot loop: {str(e)}", exc_info=True)
        finally:
            await self.shutdown()

    async def scan_markets(self) -> None:
        """
        Fetch BTC markets from Kalshi API by querying each BTC series directly.
        Updates self.markets with current market data.

        Queries by series_ticker to avoid the 200-market pagination limit hiding
        BTC markets behind unrelated sports/weather markets.
        """
        try:
            logger.debug("Scanning markets from Kalshi API...")

            btc_prefixes = self.settings.get(
                "BTC_TICKER_PREFIXES", ["KXBTC15M", "KXBTCD", "KXBTC"]
            )

            self.markets = {}  # reset each cycle

            for series in btc_prefixes:
                try:
                    response = await self.kalshi_client.get_markets(
                        series_ticker=series, status="open", limit=200
                    )
                    all_markets = (
                        response.get("markets", [])
                        if isinstance(response, dict)
                        else response
                    )
                    for market in all_markets:
                        ticker = market.get("ticker", "")
                        status = market.get("status")
                        if status not in ["active", "open"]:
                            continue
                        self.markets[ticker] = market
                        logger.debug(f"BTC market found: {ticker}")
                except Exception as e:
                    logger.debug(f"Series {series} query failed: {e}")

            logger.info(f"Markets scanned: {len(self.markets)} active BTC markets found")

        except Exception as e:
            logger.error(f"Failed to scan markets: {str(e)}")

    async def analyze_market(self, market: dict) -> None:
        """
        Analyze a single market:
        1. Fetch orderbook (only – /trades is unavailable on demo API)
        2. Run strategy signal analysis (supports both sync and async analyze())
        3. Execute entry signal if conditions met

        Args:
            market: Market data dict
        """
        ticker = market.get("ticker")

        try:
            logger.debug(f"Analyzing market: {ticker}")

            # Fetch orderbook (confirmed working on demo API)
            orderbook = await self.kalshi_client.get_orderbook(ticker)

            # Run strategy – support both sync and async analyze()
            result = self.strategy.analyze(
                ticker=ticker,
                market=market,
                orderbook=orderbook,
                recent_trades=[],
            )
            if inspect.iscoroutine(result):
                signal = await result
            else:
                signal = result

            if not signal:
                logger.debug(f"No signal for {ticker}")
                return

            logger.info(f"Signal generated for {ticker}: {signal}")

            # Execute signal
            await self.execute_signal(signal)

        except Exception as e:
            logger.error(f"Failed to analyze market {ticker}: {str(e)}")

    async def execute_signal(self, signal: dict) -> None:
        """
        Execute a trading signal.

        Flow:
        1. Risk checks (can_trade)
        2. Calculate position size
        3. Place limit order

        Args:
            signal: dict with keys:
                - ticker: market ticker
                - side: 'BUY' or 'SELL'
                - price: limit price
                - count: base count (may be adjusted for position sizing)
                - expected_value: EV or win probability
                - confidence: confidence score (0-1)
        """
        # Support both plain dicts and Signal dataclass objects
        if hasattr(signal, "metadata") and signal.metadata:
            # Signal dataclass from OrderbookMispricingStrategy
            meta = signal.metadata
            ticker = meta.get("ticker")
            kalshi_side = meta.get("side", "yes")   # "yes" or "no"
            price = signal.entry_price
            count = max(1, int(signal.position_size_usd / max(price, 0.01)))
            ev = meta.get("ev", 0.0)
            side = signal.direction  # "BUY" or "SELL" for logging
        else:
            ticker = signal.get("ticker")
            kalshi_side = "yes" if signal.get("side", "BUY").upper() == "BUY" else "no"
            side = signal.get("side", "BUY")
            price = signal.get("price")
            count = signal.get("count", 1)
            ev = signal.get("expected_value", 0)

        try:
            logger.info(f"Executing signal for {ticker}: {side} {count} @ {price:.2f}, EV={ev:.4f}")

            # Step 1: Risk checks — pass a plain dict so can_trade() works regardless of signal type
            risk_signal = {
                "ticker": ticker,
                "side": kalshi_side,
                "price": price,
                "count": count,
                "expected_value": ev,
            }
            can_trade, reason = self.risk_manager.can_trade(risk_signal)
            if not can_trade:
                logger.info(f"Signal rejected by risk manager: {reason}")
                return

            # Step 2: Position sizing (optional sophistication)
            # For now, use signal count as-is
            # Could implement Kelly criterion or other sizing here
            position_size = count

            # Step 3: Place limit order
            order_id, error = await self.order_manager.place_limit_order(
                ticker=ticker,
                side=kalshi_side,
                price=price,
                count=position_size,
            )

            if error:
                logger.error(f"Order placement failed: {error}")
                return

            logger.info(f"Order placed successfully: {order_id} for {ticker}")

            # Telegram alert
            if self.alerter:
                emoji = "🟢" if side == "BUY" else "🔴"
                msg = (
                    f"{emoji} <b>PAPER TRADE</b>\n"
                    f"<code>{ticker}</code>\n"
                    f"{side} {position_size} contracts @ {price:.2f}\n"
                    f"EV: {ev:+.1%}"
                )
                await self.alerter._send_message(msg)

            # Log execution
            self._log_execution(
                ticker=ticker,
                side=side,
                price=price,
                count=position_size,
                order_id=order_id,
                expected_value=ev,
            )

        except Exception as e:
            logger.error(f"Failed to execute signal for {ticker}: {str(e)}")

    async def manage_positions(self) -> None:
        """
        Manage open positions:
        1. Get current positions
        2. For each position, check if strategy says exit
        3. Place exit orders if needed
        4. Update P&L tracking
        """
        try:
            open_positions = await self.position_tracker.get_open_positions()

            if not open_positions:
                logger.debug("No open positions to manage")
                return

            logger.info(f"Managing {len(open_positions)} open positions")

            for position in open_positions:
                # Check exit condition
                exit_signal = self.strategy.check_exit(position)

                if exit_signal:
                    logger.info(f"Exit signal for {position.ticker}: {exit_signal}")

                    # Place exit order (opposite side) — Kalshi uses "yes"/"no"
                    exit_side = "no" if position.side in ("BUY", "yes") else "yes"
                    exit_price = exit_signal.get("price")
                    exit_count = position.quantity

                    order_id, error = await self.order_manager.place_limit_order(
                        ticker=position.ticker,
                        side=exit_side,
                        price=exit_price,
                        count=exit_count,
                    )

                    if not error:
                        logger.info(f"Exit order placed: {order_id} for {position.ticker}")
                        # In a real system, would track this as part of position lifecycle
                    else:
                        logger.error(f"Failed to place exit order: {error}")

            # Update unrealized P&L
            current_prices = await self._fetch_current_prices()
            unrealized_pnl = self.position_tracker.calculate_unrealized_pnl(current_prices)
            self.risk_manager.set_unrealized_pnl(unrealized_pnl)

        except Exception as e:
            logger.error(f"Failed to manage positions: {str(e)}")

    async def sync_positions_with_api(self) -> None:
        """
        Reconcile local position state with Kalshi API.
        Useful to call periodically to catch any discrepancies.
        """
        try:
            logger.info("Syncing positions with Kalshi API...")
            await self.position_tracker.sync_positions(self.kalshi_client)
            logger.info("Position sync complete")
        except Exception as e:
            logger.error(f"Failed to sync positions: {str(e)}")

    async def sync_orders_with_api(self) -> None:
        """
        Reconcile local order state with Kalshi API.
        """
        try:
            logger.info("Syncing orders with Kalshi API...")
            await self.order_manager.sync_orders_from_api()
            logger.info("Order sync complete")
        except Exception as e:
            logger.error(f"Failed to sync orders: {str(e)}")

    # --- Private Methods ---

    async def _fetch_current_prices(self) -> Dict[str, float]:
        """
        Fetch current prices for all open positions.

        Returns:
            dict of ticker -> current_price
        """
        prices = {}
        try:
            open_positions = await self.position_tracker.get_open_positions()
            for position in open_positions:
                ticker = position.ticker
                # Try cached market data first
                market = self.markets.get(ticker, {})
                current_price = market.get("last_price", 0)
                if current_price:
                    prices[ticker] = current_price
                else:
                    # Fetch from orderbook if not in market cache
                    try:
                        orderbook = await self.kalshi_client.get_orderbook(ticker)
                        ob = orderbook.get("orderbook", orderbook)
                        yes_levels = ob.get("yes", [])
                        if yes_levels:
                            best_bid = max(lvl[0] for lvl in yes_levels) / 100.0
                            prices[ticker] = best_bid
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Failed to fetch current prices: {str(e)}")

        return prices

    def _log_execution(
        self, ticker: str, side: str, price: float, count: int,
        order_id: str, expected_value: float
    ) -> None:
        """Log order execution details."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": "order_executed",
            "ticker": ticker,
            "side": side,
            "price": price,
            "count": count,
            "order_id": order_id,
            "expected_value": expected_value,
        }
        logger.info(f"EXECUTION: {json.dumps(log_data)}")

    def _log_metrics(self) -> None:
        """Log overall bot metrics."""
        try:
            risk_metrics = self.risk_manager.get_metrics()
            order_metrics = self.order_manager.get_metrics()
            position_metrics = self.position_tracker.get_metrics()

            metrics = {
                "timestamp": datetime.utcnow().isoformat(),
                "cycle_count": self.cycle_count,
                "risk": risk_metrics,
                "orders": order_metrics,
                "positions": position_metrics,
            }

            logger.info(f"METRICS: {json.dumps(metrics, indent=2)}")

        except Exception as e:
            logger.error(f"Failed to log metrics: {str(e)}")

    def stop(self) -> None:
        """Stop the bot gracefully."""
        logger.info("Stopping bot...")
        self.is_running = False


class MockStrategy:
    """
    Mock strategy for testing/demo purposes.
    Replace with actual strategy implementation.
    """

    def __init__(self):
        self.counter = 0

    def analyze(
        self, ticker: str, market: dict, orderbook: dict, recent_trades: list
    ) -> Optional[dict]:
        """
        Generate a signal based on market data.

        Returns:
            Signal dict or None if no signal
        """
        # Mock: every 5th call, generate a signal
        self.counter += 1
        if self.counter % 5 != 0:
            return None

        # Mock signal
        return {
            "ticker": ticker,
            "side": "BUY" if self.counter % 10 == 5 else "SELL",
            "price": market.get("last_price", 50000),
            "count": 1,
            "expected_value": 0.05,  # 5% expected edge
            "confidence": 0.6,
        }

    def check_exit(self, position) -> Optional[dict]:
        """
        Check if position should be exited.

        Returns:
            Exit signal dict or None
        """
        # Mock: no exit signals
        return None
