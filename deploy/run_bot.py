"""
Main entry point for the Kalshi Bitcoin Trading Bot.

Usage:
    # Paper trade on Kalshi demo environment (safe, no real money):
    python deploy/run_bot.py --paper

    # Paper trade with $1000 simulated bankroll:
    python deploy/run_bot.py --paper --bankroll 1000

    # Run specific strategy:
    python deploy/run_bot.py --paper --strategy ensemble

    # Verbose debug output:
    python deploy/run_bot.py --paper --log-level DEBUG

    # Live trading on demo environment (real API calls, no real money):
    python deploy/run_bot.py --env demo

    # LIVE TRADING (real money - be careful):
    python deploy/run_bot.py --env prod
"""

import asyncio
import argparse
import signal
import sys
import os
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional
import json

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from monitoring.logger import setup_logging, get_logger, log_trade
from monitoring.alerter import Alerter


logger = get_logger(__name__)


class PaperTradingEngine:
    """
    Paper trading engine that simulates order execution against live Kalshi market data.

    In paper mode, the bot:
    - Reads REAL market data from Kalshi (live prices, order books)
    - Simulates order fills based on real bid/ask prices
    - Tracks a virtual bankroll (never touches real money)
    - Produces identical logs/alerts to live mode so you can evaluate performance

    This lets you calibrate the strategy without financial risk.
    """

    def __init__(self, starting_bankroll: float, settings):
        self.bankroll = starting_bankroll
        self.initial_bankroll = starting_bankroll
        self.settings = settings
        self.positions = {}          # ticker -> {side, count, avg_price, entry_time}
        self.open_orders = []        # list of pending simulated orders
        self.trade_history = []      # all fills
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_date = date.today()
        self._order_id_counter = 0

        logger.info(f"[PAPER] Engine initialized with ${starting_bankroll:.2f} virtual bankroll")

    def _next_order_id(self) -> str:
        self._order_id_counter += 1
        return f"PAPER-{self._order_id_counter:06d}"

    def reset_daily_if_needed(self):
        today = date.today()
        if today != self.last_reset_date:
            logger.info(f"[PAPER] New day — resetting daily P&L. Yesterday: ${self.daily_pnl:+.2f}")
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset_date = today

    def place_order(self, ticker: str, side: str, price: float, count: int) -> dict:
        """Simulate placing a limit order. Returns a fake order dict."""
        order_id = self._next_order_id()
        order = {
            "order_id": order_id,
            "ticker": ticker,
            "side": side.upper(),   # YES or NO
            "price": price,
            "count": count,
            "status": "resting",
            "created_at": datetime.utcnow().isoformat(),
        }
        self.open_orders.append(order)
        logger.info(
            f"[PAPER] Order placed: {order_id} | {side} {count}x {ticker} @ ${price:.2f}"
        )
        return order

    def try_fill_orders(self, ticker: str, best_ask: float, best_bid: float):
        """
        Simulate fills: a BUY limit fills if our price >= best_ask; SELL fills if price <= best_bid.
        This mimics how resting limit orders get matched on a real order book.
        """
        filled = []
        remaining = []

        for order in self.open_orders:
            if order["ticker"] != ticker:
                remaining.append(order)
                continue

            side = order["side"]
            price = order["price"]
            count = order["count"]
            filled_this = False

            # BUY YES contract: fills when market's ask comes down to our limit
            if side == "YES" and best_ask <= price:
                fill_price = best_ask  # we get the ask (slightly better than limit in simulation)
                self._record_fill(order, fill_price)
                filled_this = True

            # SELL YES (exit long): fills when bid reaches our limit
            elif side == "NO" and best_bid >= price:
                fill_price = best_bid
                self._record_fill(order, fill_price)
                filled_this = True

            if not filled_this:
                remaining.append(order)
            else:
                filled.append(order)

        self.open_orders = remaining
        return filled

    def _record_fill(self, order: dict, fill_price: float):
        """Record a fill and update paper positions."""
        ticker = order["ticker"]
        side = order["side"]
        count = order["count"]
        cost = fill_price * count  # dollar cost (price is in cents on Kalshi, 0-1 scale here)

        if side == "YES":
            # Opening / adding to a long position
            if ticker in self.positions:
                pos = self.positions[ticker]
                total_count = pos["count"] + count
                avg_price = (pos["avg_price"] * pos["count"] + fill_price * count) / total_count
                pos["count"] = total_count
                pos["avg_price"] = avg_price
            else:
                self.positions[ticker] = {
                    "side": "YES",
                    "count": count,
                    "avg_price": fill_price,
                    "entry_time": datetime.utcnow().isoformat(),
                }
            self.bankroll -= cost
            action = "BUY"

        else:
            # Closing / reducing a long position
            if ticker in self.positions:
                pos = self.positions[ticker]
                entry_price = pos["avg_price"]
                pnl = (fill_price - entry_price) * count
                self.bankroll += fill_price * count  # receive proceeds
                self.daily_pnl += pnl

                if count >= pos["count"]:
                    del self.positions[ticker]
                else:
                    pos["count"] -= count
            else:
                # Shorting (selling NO contracts)
                self.bankroll -= (1 - fill_price) * count
            action = "SELL"

        fill_record = {
            "order_id": order["order_id"],
            "ticker": ticker,
            "action": action,
            "side": side,
            "fill_price": fill_price,
            "count": count,
            "bankroll_after": self.bankroll,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.trade_history.append(fill_record)
        self.daily_trades += 1

        logger.info(
            f"[PAPER] FILL: {action} {count}x {ticker} @ ${fill_price:.3f} | "
            f"Bankroll: ${self.bankroll:.2f} | Daily P&L: ${self.daily_pnl:+.2f}"
        )
        log_trade(action, ticker, side, fill_price, count, 0.0)

    def calculate_unrealized_pnl(self, current_prices: dict) -> float:
        """Calculate total unrealized P&L across all open positions."""
        total = 0.0
        for ticker, pos in self.positions.items():
            if ticker in current_prices:
                current = current_prices[ticker]
                total += (current - pos["avg_price"]) * pos["count"]
        return total

    def get_stats(self) -> dict:
        """Compute win rate, profit factor, and other stats from trade history."""
        if not self.trade_history:
            return {"total_trades": 0, "win_rate": 0, "profit_factor": 0, "sharpe_ratio": 0, "avg_trade_pnl": 0}

        import numpy as np
        # Pair buys and sells to compute per-trade P&L
        pnls = []
        buy_prices = {}
        for t in self.trade_history:
            if t["action"] == "BUY":
                buy_prices[t["ticker"]] = t["fill_price"]
            elif t["action"] == "SELL" and t["ticker"] in buy_prices:
                pnl = (t["fill_price"] - buy_prices[t["ticker"]]) * t["count"]
                pnls.append(pnl)
                del buy_prices[t["ticker"]]

        if not pnls:
            return {"total_trades": 0, "win_rate": 0, "profit_factor": 0, "sharpe_ratio": 0, "avg_trade_pnl": 0}

        pnls = np.array(pnls)
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = len(wins) / len(pnls) * 100
        profit_factor = (wins.sum() / abs(losses.sum())) if len(losses) > 0 and losses.sum() != 0 else float('inf')
        avg_pnl = pnls.mean()

        # Sharpe (annualized from trade returns)
        if len(pnls) > 1 and pnls.std() > 0:
            sharpe = (pnls.mean() / pnls.std()) * (252 ** 0.5)
        else:
            sharpe = 0.0

        return {
            "total_trades": len(pnls),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "avg_trade_pnl": round(float(avg_pnl), 4),
        }

    def print_summary(self):
        """Print a summary of paper trading performance."""
        stats = self.get_stats()
        total_pnl = self.bankroll - self.initial_bankroll
        roi = (total_pnl / self.initial_bankroll) * 100
        unrealized = self.calculate_unrealized_pnl({})  # would need prices

        print("\n" + "=" * 70)
        print("📊 PAPER TRADING SUMMARY")
        print("=" * 70)
        print(f"  Initial Bankroll:  ${self.initial_bankroll:,.2f}")
        print(f"  Current Bankroll:  ${self.bankroll:,.2f}")
        print(f"  Total P&L:         ${total_pnl:+,.2f}  ({roi:+.1f}%)")
        print(f"  Daily P&L:         ${self.daily_pnl:+,.2f}")
        print(f"  Open Positions:    {len(self.positions)}")
        print(f"  Total Trades:      {stats['total_trades']}")
        print(f"  Win Rate:          {stats['win_rate']}%")
        print(f"  Profit Factor:     {stats['profit_factor']}x")
        print(f"  Sharpe Ratio:      {stats['sharpe_ratio']}")
        print(f"  Avg Trade P&L:     ${stats['avg_trade_pnl']:+.4f}")
        print("=" * 70)


class BotRunner:
    """
    Main runner that wires together: KalshiClient, Strategy, RiskManager,
    OrderManager, PositionTracker, and Trader — then runs the trading loop.
    """

    def __init__(self, args):
        self.args = args
        self.running = True
        self.paper_engine: Optional[PaperTradingEngine] = None
        self.kalshi_client = None
        self.trader = None
        self.alerter = None
        self.cycle_count = 0

    async def setup(self):
        """Initialize all components."""
        from config.settings import Settings

        # Override bankroll from CLI if provided
        if self.args.bankroll:
            os.environ["STARTING_BANKROLL"] = str(self.args.bankroll)
        if self.args.env:
            os.environ["KALSHI_ENV"] = self.args.env

        try:
            settings = Settings()
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            logger.error("Make sure you've created a .env file from .env.example and filled in your API credentials.")
            sys.exit(1)

        # Alerter (Telegram or console fallback)
        self.alerter = Alerter()

        # Paper trading engine
        if self.args.paper:
            bankroll = float(self.args.bankroll) if self.args.bankroll else settings.STARTING_BANKROLL
            self.paper_engine = PaperTradingEngine(bankroll, settings)
            logger.info(f"[PAPER MODE] Virtual bankroll: ${bankroll:.2f}")

        # Kalshi API client
        from data.kalshi_client import KalshiClient
        self.kalshi_client = KalshiClient(
            api_key_id=settings.KALSHI_API_KEY_ID,
            private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
            base_url=settings.base_url,
            paper_trade=self.args.paper,
        )

        # Strategy
        strategy_name = self.args.strategy
        strategy = self._load_strategy(strategy_name, settings)

        # Risk manager
        from bot.risk_manager import RiskManager
        from bot.position_tracker import PositionTracker
        position_tracker = PositionTracker()
        risk_manager = RiskManager(settings, position_tracker)

        # Order manager
        from bot.order_manager import OrderManager
        order_manager = OrderManager(self.kalshi_client, settings)

        # Trader
        from bot.trader import Trader
        trader_settings = {
            "TARGET_TICKERS": [],  # dynamically discovered each cycle
            "CYCLE_INTERVAL": settings.SCAN_INTERVAL_SECONDS,
            "LOG_METRICS_INTERVAL": 300,
            "BTC_TICKER_PREFIXES": [settings.BTC_15M_TICKER],  # 15M contracts only
        }
        self.trader = Trader(
            kalshi_client=self.kalshi_client,
            strategy=strategy,
            risk_manager=risk_manager,
            order_manager=order_manager,
            position_tracker=position_tracker,
            settings=trader_settings,
            alerter=self.alerter,
        )
        await self.trader.initialize()

        # Attach paper engine to trader for position tracking
        if self.paper_engine:
            self.trader.paper_engine = self.paper_engine
            self.trader.bankroll = self.paper_engine.bankroll
            self.trader.initial_bankroll = self.paper_engine.initial_bankroll
            self.trader.daily_pnl = self.paper_engine.daily_pnl
            self.trader.recent_trades = self.paper_engine.trade_history
            self.trader.active_orders = self.paper_engine.open_orders
            self.trader.stats = {}

        mode_str = "PAPER TRADING" if self.args.paper else f"LIVE ({self.args.env.upper()})"
        bankroll_str = f"${float(self.args.bankroll):.2f}" if self.args.bankroll else f"${settings.STARTING_BANKROLL:.2f}"

        logger.info("=" * 70)
        logger.info(f"  Kalshi Bitcoin Trading Bot")
        logger.info(f"  Mode:       {mode_str}")
        logger.info(f"  Strategy:   {strategy_name}")
        logger.info(f"  Bankroll:   {bankroll_str}")
        logger.info(f"  Scan every: {settings.SCAN_INTERVAL_SECONDS}s")
        logger.info(f"  Max loss/day: ${settings.MAX_DAILY_LOSS:.2f}")
        logger.info(f"  Min edge:   {settings.MIN_EDGE_THRESHOLD*100:.0f}%")
        logger.info(f"  Kelly frac: {settings.KELLY_FRACTION}x")
        logger.info("=" * 70)

        # Start web dashboard in background thread (dies with the bot process)
        import threading
        from http.server import HTTPServer
        from deploy.webdash import Handler as DashHandler
        def _run_dash():
            try:
                srv = HTTPServer(("localhost", 8081), DashHandler)
                srv.serve_forever()
            except Exception as e:
                logger.warning(f"Dashboard server error: {e}")
        t = threading.Thread(target=_run_dash, daemon=True, name="webdash")
        t.start()
        logger.info("Dashboard running at http://localhost:8081")

        await self.alerter.send_status(
            f"Bot started | {mode_str} | Strategy: {strategy_name} | Bankroll: {bankroll_str}"
        )

    def _load_strategy(self, name: str, settings):
        """Instantiate the requested strategy."""
        from strategies.ensemble_strategy import EnsembleStrategy
        from strategies.momentum_strategy import MomentumStrategy
        from strategies.mean_reversion_strategy import MeanReversionStrategy
        from strategies.cvd_divergence_strategy import CVDDivergenceStrategy
        from strategies.orderbook_strategy import OrderbookMispricingStrategy

        strategy_settings = {
            "kelly_fraction": settings.KELLY_FRACTION,
            "min_edge": settings.MIN_EDGE_THRESHOLD,
            "max_position_size": settings.MAX_POSITION_SIZE,
        }

        strategies = {
            "orderbook": OrderbookMispricingStrategy,
            "ensemble": EnsembleStrategy,
            "momentum": MomentumStrategy,
            "macd": MomentumStrategy,
            "mean_reversion": MeanReversionStrategy,
            "rsi": MeanReversionStrategy,
            "cvd": CVDDivergenceStrategy,
        }
        cls = strategies.get(name, OrderbookMispricingStrategy)
        return cls(name=name, settings=strategy_settings)

    async def run(self):
        """Main trading loop."""
        try:
            await self.setup()
        except Exception as e:
            logger.error(f"Setup failed: {e}", exc_info=True)
            sys.exit(1)

        scan_interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "120"))

        while self.running:
            try:
                self.cycle_count += 1
                logger.info(f"--- Cycle #{self.cycle_count} ---")

                # Reset daily tracking if new day
                if self.paper_engine:
                    self.paper_engine.reset_daily_if_needed()

                # Run one full trading cycle
                await self.trader.run_cycle()

                # Sync paper engine state to trader for dashboard
                if self.paper_engine:
                    self.trader.bankroll = self.paper_engine.bankroll
                    self.trader.daily_pnl = self.paper_engine.daily_pnl
                    self.trader.stats = self.paper_engine.get_stats()

                # Check settlement results for expired paper orders
                from bot.settlement_tracker import check_and_record
                from monitoring.logger import get_logger as _gl
                import re as _re, json as _json
                _log_path = Path(__file__).parent.parent / "logs" / "bot.log"
                _paper_trades = []
                try:
                    for _line in _log_path.read_text(errors="replace").splitlines():
                        if "EXECUTION:" in _line:
                            _js = _line[_line.index("EXECUTION:") + 10:].strip()
                            _paper_trades.append(_json.loads(_js))
                except Exception:
                    pass
                if _paper_trades:
                    settlements = await check_and_record(self.kalshi_client, _paper_trades)
                    settled_pnl = sum(s["total_pnl"] for s in settlements.values() if s["result"] in ("yes", "no"))
                    if settlements:
                        logger.info(f"Settlements: {len(settlements)} contracts settled | Total P&L: ${settled_pnl:+.2f}")

                # Send periodic P&L alerts (every 10 cycles)
                if self.cycle_count % 10 == 0:
                    if self.paper_engine:
                        await self.alerter.send_pnl_alert(self.paper_engine.daily_pnl)

                logger.info(f"Sleeping {scan_interval}s until next cycle...")
                await asyncio.sleep(scan_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)
                await self.alerter.send_error_alert(str(e))
                await asyncio.sleep(30)  # short pause after error before retry

        await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down...")
        self.running = False

        try:
            if self.trader:
                await self.trader.shutdown()
        except Exception as e:
            logger.error(f"Error during trader shutdown: {e}")

        if self.paper_engine:
            self.paper_engine.print_summary()

        if self.alerter:
            await self.alerter.send_status("Bot shut down cleanly.")

        logger.info("Shutdown complete.")


def setup_signal_handlers(runner: BotRunner, loop: asyncio.AbstractEventLoop):
    """Register SIGINT/SIGTERM for graceful Ctrl+C shutdown."""
    def _handle(sig):
        logger.info(f"Signal {sig.name} received — shutting down...")
        runner.running = False
        # Schedule shutdown coroutine
        loop.create_task(runner.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handle(s))
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler


async def main():
    parser = argparse.ArgumentParser(
        description="Kalshi Bitcoin Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy/run_bot.py --paper                        # paper trade, $100 bankroll
  python deploy/run_bot.py --paper --bankroll 1000        # paper trade, $1000 bankroll
  python deploy/run_bot.py --paper --strategy ensemble    # paper trade with ensemble strategy
  python deploy/run_bot.py --paper --log-level DEBUG      # verbose debug output
  python deploy/run_bot.py --env demo                     # live demo (real API, no real money)
  python deploy/run_bot.py --env prod                     # LIVE TRADING (real money!)
        """
    )
    parser.add_argument(
        "--paper", action="store_true",
        help="Paper trade mode: simulate fills against live data, no real orders placed"
    )
    parser.add_argument(
        "--bankroll", type=float, default=None,
        help="Starting bankroll (overrides STARTING_BANKROLL in .env). Default: 100.0"
    )
    parser.add_argument(
        "--strategy", choices=["orderbook", "ensemble", "momentum", "macd", "mean_reversion", "rsi", "cvd"],
        default="orderbook",
        help="Trading strategy to use (default: orderbook)"
    )
    parser.add_argument(
        "--env", choices=["demo", "prod"], default="demo",
        help="Kalshi environment: demo (no real money) or prod (real money). Default: demo"
    )
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO",
        help="Log verbosity (default: INFO). Use DEBUG to see every signal calculation."
    )
    parser.add_argument(
        "--scan-interval", type=int, default=None,
        help="Seconds between market scans (overrides .env SCAN_INTERVAL_SECONDS)"
    )

    args = parser.parse_args()

    # Setup logging before anything else
    log_level = getattr(logging, args.log_level)
    setup_logging(log_level)

    # Override scan interval from CLI
    if args.scan_interval:
        os.environ["SCAN_INTERVAL_SECONDS"] = str(args.scan_interval)

    # Safety gate for live trading
    if args.env == "prod" and not args.paper:
        print("\n⚠️  WARNING: You are about to run LIVE trading with REAL money on Kalshi.")
        print("   Make sure you've run paper trading and are satisfied with performance.")
        confirm = input("   Type 'CONFIRM' to proceed: ").strip()
        if confirm != "CONFIRM":
            print("Aborted.")
            return

    runner = BotRunner(args)
    loop = asyncio.get_event_loop()
    setup_signal_handlers(runner, loop)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
