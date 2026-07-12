"""
Backtesting runner for executing and comparing strategy backtests.
"""

import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .engine import BacktestEngine
from ..monitoring.logger import get_logger

logger = get_logger(__name__)


class BacktestRunner:
    """Runs backtests for strategies and generates results."""

    BENCHMARK_CRITERIA = {
        'win_rate': 55,  # Minimum 55%
        'profit_factor': 1.5,  # Minimum 1.5x
        'max_drawdown': 20,  # Maximum 20%
    }

    def __init__(self):
        """Initialize backtesting runner."""
        self.results_dir = Path(__file__).parent / "results"
        self.results_dir.mkdir(exist_ok=True)

    def run_backtest(
        self,
        strategy,
        ticker: str,
        initial_bankroll: float = 10000,
        days: int = 30,
        settings: Optional[Dict] = None
    ) -> Dict:
        """
        Run a single backtest.

        Args:
            strategy: Strategy instance
            ticker: Contract ticker
            initial_bankroll: Starting capital
            days: Number of days to backtest
            settings: Strategy settings

        Returns:
            Dictionary with backtest results
        """
        if settings is None:
            settings = {
                'taker_fee': 0.005,
                'default_size': 1.0,
            }

        logger.info(f"Running backtest for {strategy.__class__.__name__} on {ticker}")

        # Note: In real implementation, this would fetch historical data
        # For now, returning a template structure
        logger.warning("Backtesting requires historical data source - implement data fetching")

        return {
            'strategy': strategy.__class__.__name__,
            'ticker': ticker,
            'days': days,
            'status': 'data_not_available',
        }

    def run_all_strategies(
        self,
        strategies: List,
        ticker: str = 'KXBTC15M',
        initial_bankroll: float = 10000,
        days: int = 30,
    ) -> List[Dict]:
        """
        Run backtests for all provided strategies.

        Args:
            strategies: List of strategy instances
            ticker: Contract ticker
            initial_bankroll: Starting capital
            days: Number of days to backtest

        Returns:
            List of results
        """
        results = []

        for strategy in strategies:
            try:
                result = self.run_backtest(
                    strategy=strategy,
                    ticker=ticker,
                    initial_bankroll=initial_bankroll,
                    days=days,
                )
                result['passed'] = self._check_benchmarks(result.get('metrics', {}))
                results.append(result)
            except Exception as e:
                logger.error(f"Backtest failed for {strategy.__class__.__name__}: {str(e)}")
                results.append({
                    'strategy': strategy.__class__.__name__,
                    'status': 'failed',
                    'error': str(e),
                    'passed': False,
                })

        return results

    def print_results(self, results: List[Dict]):
        """
        Print formatted backtest results.

        Args:
            results: List of backtest results
        """
        print("\n" + "=" * 120)
        print("BACKTEST RESULTS")
        print("=" * 120)

        header = (
            f"{'Strategy':<25} {'Win Rate':<12} {'Profit Factor':<15} {'Max DD':<12} "
            f"{'Total Return':<15} {'Sharpe':<10} {'Trades':<8} {'Pass':<6}"
        )
        print(header)
        print("-" * 120)

        for result in results:
            if result.get('status') == 'failed':
                print(f"{result.get('strategy', 'Unknown'):<25} FAILED")
                continue

            metrics = result.get('metrics', {})
            strategy_name = result.get('strategy', 'Unknown')
            win_rate = metrics.get('win_rate', 0)
            profit_factor = metrics.get('profit_factor', 0)
            max_dd = metrics.get('max_drawdown', 0)
            total_return = metrics.get('total_return_percent', 0)
            sharpe = metrics.get('sharpe_ratio', 0)
            trades = metrics.get('total_trades', 0)
            passed = "PASS" if result.get('passed', False) else "FAIL"

            print(
                f"{strategy_name:<25} {win_rate:>10.1f}% {profit_factor:>13.2f}x {max_dd:>10.1f}% "
                f"{total_return:>13.2f}% {sharpe:>8.2f} {trades:>7} {passed:>5}"
            )

        print("=" * 120)

    def save_results(self, results: List[Dict], filename: Optional[str] = None):
        """
        Save backtest results to file.

        Args:
            results: List of backtest results
            filename: Output filename (optional)
        """
        if filename is None:
            filename = f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        output_path = self.results_dir / filename

        try:
            # Flatten results for CSV
            rows = []
            for result in results:
                metrics = result.get('metrics', {})
                row = {
                    'strategy': result.get('strategy'),
                    'ticker': result.get('ticker'),
                    'days': result.get('days'),
                    'win_rate': metrics.get('win_rate', 0),
                    'profit_factor': metrics.get('profit_factor', 0),
                    'max_drawdown': metrics.get('max_drawdown', 0),
                    'total_return': metrics.get('total_return_percent', 0),
                    'sharpe_ratio': metrics.get('sharpe_ratio', 0),
                    'total_trades': metrics.get('total_trades', 0),
                    'avg_trade_pnl': metrics.get('avg_trade_pnl', 0),
                    'passed': result.get('passed', False),
                    'timestamp': datetime.now().isoformat(),
                }
                rows.append(row)

            df = pd.DataFrame(rows)
            df.to_csv(output_path, index=False)
            logger.info(f"Backtest results saved to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save backtest results: {str(e)}")

    def _check_benchmarks(self, metrics: Dict) -> bool:
        """
        Check if metrics pass benchmark criteria.

        Args:
            metrics: Metrics dictionary

        Returns:
            True if all benchmarks passed
        """
        win_rate = metrics.get('win_rate', 0)
        profit_factor = metrics.get('profit_factor', 0)
        max_drawdown = metrics.get('max_drawdown', 0)

        passed = (
            win_rate >= self.BENCHMARK_CRITERIA['win_rate'] and
            profit_factor >= self.BENCHMARK_CRITERIA['profit_factor'] and
            max_drawdown <= self.BENCHMARK_CRITERIA['max_drawdown']
        )

        return passed
