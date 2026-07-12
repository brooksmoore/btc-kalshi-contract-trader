"""
Backtest runner script for the Kalshi trading bot.

Usage:
    python deploy/run_backtest.py --strategy macd --days 30 --ticker KXBTC15M
    python deploy/run_backtest.py --all
"""

import argparse
from pathlib import Path
from typing import List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.runner import BacktestRunner
from monitoring.logger import setup_logging, get_logger
import logging


logger = get_logger(__name__)


STRATEGY_CHOICES = {
    'macd': 'MACDStrategy',
    'rsi': 'RSIStrategy',
    'cvd': 'CVDStrategy',
    'ensemble': 'EnsembleStrategy',
}


def run_single_backtest(
    strategy_name: str,
    ticker: str = 'KXBTC15M',
    days: int = 30,
    initial_bankroll: float = 10000,
):
    """
    Run a single backtest.

    Args:
        strategy_name: Strategy name (macd, rsi, cvd, ensemble)
        ticker: Contract ticker
        days: Number of days to backtest
        initial_bankroll: Starting capital
    """
    logger.info(f"Running backtest for {strategy_name}")

    runner = BacktestRunner()

    # TODO: Instantiate the actual strategy class
    # For now, this is a template that shows the structure

    logger.warning(f"Strategy {strategy_name} not yet implemented in backtest runner")
    logger.info("Implement strategy loading and backtesting")

    return {
        'strategy': strategy_name,
        'status': 'not_implemented',
    }


def run_all_backtests(
    ticker: str = 'KXBTC15M',
    days: int = 30,
    initial_bankroll: float = 10000,
):
    """
    Run backtests for all strategies.

    Args:
        ticker: Contract ticker
        days: Number of days to backtest
        initial_bankroll: Starting capital
    """
    logger.info(f"Running backtests for all strategies over {days} days")

    runner = BacktestRunner()
    results = []

    for strategy_key, strategy_class in STRATEGY_CHOICES.items():
        logger.info(f"Backtesting {strategy_key}...")

        # TODO: Instantiate actual strategy and run backtest
        result = {
            'strategy': strategy_key,
            'status': 'not_implemented',
        }
        results.append(result)

    runner.print_results(results)
    runner.save_results(results)

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Kalshi Trading Bot - Backtest Runner'
    )
    parser.add_argument(
        '--strategy',
        choices=list(STRATEGY_CHOICES.keys()),
        help='Run backtest for specific strategy'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Run backtests for all strategies'
    )
    parser.add_argument(
        '--ticker',
        default='KXBTC15M',
        help='Contract ticker (default: KXBTC15M)'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of days to backtest (default: 30)'
    )
    parser.add_argument(
        '--bankroll',
        type=float,
        default=10000,
        help='Initial bankroll (default: 10000)'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level'
    )

    args = parser.parse_args()

    # Setup logging
    log_level = getattr(logging, args.log_level)
    setup_logging(log_level)

    logger.info("=" * 80)
    logger.info("Kalshi Bitcoin Trading Bot - Backtest Runner")
    logger.info("=" * 80)

    if args.all:
        logger.info(f"Running all strategies: ticker={args.ticker}, days={args.days}")
        results = run_all_backtests(
            ticker=args.ticker,
            days=args.days,
            initial_bankroll=args.bankroll,
        )
    elif args.strategy:
        logger.info(
            f"Running {args.strategy}: ticker={args.ticker}, days={args.days}"
        )
        result = run_single_backtest(
            strategy_name=args.strategy,
            ticker=args.ticker,
            days=args.days,
            initial_bankroll=args.bankroll,
        )
        results = [result]

        runner = BacktestRunner()
        runner.print_results(results)
        runner.save_results(results)
    else:
        parser.print_help()
        logger.error("Please specify --strategy or --all")
        sys.exit(1)

    logger.info("Backtest completed")


if __name__ == '__main__':
    main()
