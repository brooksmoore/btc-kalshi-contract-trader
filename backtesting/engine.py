"""
Backtesting engine for the Kalshi trading bot.
Simulates strategy execution on historical data.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from ..monitoring.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestTrade:
    """Represents a single trade during backtesting."""
    entry_time: datetime
    entry_price: float
    entry_size: float
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    side: str  # BUY or SELL
    pnl: float
    pnl_percent: float


class BacktestEngine:
    """Backtesting engine that simulates strategy execution on historical data."""

    def __init__(self, strategy, initial_bankroll: float, settings: Dict):
        """
        Initialize backtesting engine.

        Args:
            strategy: Strategy instance with generate_signal() method
            initial_bankroll: Starting capital
            settings: Strategy settings (fees, leverage, etc.)
        """
        self.strategy = strategy
        self.initial_bankroll = initial_bankroll
        self.settings = settings

        self.bankroll = initial_bankroll
        self.trades: List[BacktestTrade] = []
        self.equity_curve = [initial_bankroll]
        self.entry_price = None
        self.entry_size = None
        self.entry_time = None
        self.position = None  # BUY or SELL or None

        # Metrics
        self.max_bankroll = initial_bankroll
        self.min_bankroll = initial_bankroll

    def run(self, candles_df: pd.DataFrame, trades_df: Optional[pd.DataFrame] = None) -> bool:
        """
        Run backtest on historical data.

        Args:
            candles_df: DataFrame with OHLCV data
            trades_df: DataFrame with trade data (optional for fill simulation)

        Returns:
            True if backtest completed successfully
        """
        if candles_df.empty:
            logger.error("Empty candles DataFrame provided to backtest")
            return False

        # Ensure required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in candles_df.columns for col in required_cols):
            logger.error(f"Missing required columns. Need: {required_cols}")
            return False

        # Reset state
        self.bankroll = self.initial_bankroll
        self.trades = []
        self.equity_curve = [self.initial_bankroll]
        self.position = None
        self.entry_price = None
        self.entry_size = None
        self.entry_time = None

        # Iterate through candles
        for idx, (timestamp, row) in enumerate(candles_df.iterrows()):
            # Get signal from strategy
            signal = self.strategy.generate_signal(candles_df.iloc[:idx+1])

            if signal is None:
                continue

            signal_type = signal.get('type')  # BUY, SELL, HOLD
            limit_price = signal.get('price')
            size = signal.get('size', self.settings.get('default_size', 1))
            kelly_fraction = signal.get('kelly_fraction', 0.25)

            # Apply Kelly sizing
            if kelly_fraction and kelly_fraction > 0:
                max_size = (self.bankroll * kelly_fraction) / limit_price
                size = min(size, max_size)

            # Check if signal is fill-able
            candle_high = row['high']
            candle_low = row['low']
            candle_close = row['close']

            if signal_type == 'BUY':
                # Check if we can buy at limit price
                if limit_price <= candle_high and not self.position:
                    # BUY signal: limit price within candle range
                    fill_price = max(limit_price, candle_low)

                    # Calculate fees (assume taker fee of 0.5%)
                    taker_fee = self.settings.get('taker_fee', 0.005)
                    fee_cost = fill_price * size * taker_fee
                    cost = (fill_price * size) + fee_cost

                    if cost <= self.bankroll:
                        self.entry_price = fill_price
                        self.entry_size = size
                        self.entry_time = timestamp
                        self.position = 'LONG'
                        self.bankroll -= cost

            elif signal_type == 'SELL':
                # Check if we can sell at limit price
                if limit_price >= candle_low and self.position == 'LONG':
                    # SELL signal: limit price within candle range
                    fill_price = min(limit_price, candle_high)

                    # Calculate exit
                    proceeds = (fill_price * self.entry_size)
                    taker_fee = self.settings.get('taker_fee', 0.005)
                    fee_cost = proceeds * taker_fee
                    net_proceeds = proceeds - fee_cost

                    self.bankroll += net_proceeds

                    # Record trade
                    pnl = net_proceeds - (self.entry_price * self.entry_size)
                    pnl_percent = (pnl / (self.entry_price * self.entry_size)) * 100

                    trade = BacktestTrade(
                        entry_time=self.entry_time,
                        entry_price=self.entry_price,
                        entry_size=self.entry_size,
                        exit_time=timestamp,
                        exit_price=fill_price,
                        side='LONG',
                        pnl=pnl,
                        pnl_percent=pnl_percent
                    )
                    self.trades.append(trade)

                    self.position = None
                    self.entry_price = None
                    self.entry_size = None
                    self.entry_time = None

            # Track equity
            self.equity_curve.append(self.bankroll)
            self.max_bankroll = max(self.max_bankroll, self.bankroll)
            self.min_bankroll = min(self.min_bankroll, self.bankroll)

        # Close any open position at final price
        if self.position and len(candles_df) > 0:
            final_price = candles_df.iloc[-1]['close']
            proceeds = (final_price * self.entry_size)
            net_proceeds = proceeds * (1 - self.settings.get('taker_fee', 0.005))
            self.bankroll += net_proceeds

            pnl = net_proceeds - (self.entry_price * self.entry_size)
            pnl_percent = (pnl / (self.entry_price * self.entry_size)) * 100

            trade = BacktestTrade(
                entry_time=self.entry_time,
                entry_price=self.entry_price,
                entry_size=self.entry_size,
                exit_time=candles_df.index[-1],
                exit_price=final_price,
                side='LONG',
                pnl=pnl,
                pnl_percent=pnl_percent
            )
            self.trades.append(trade)

        logger.info(f"Backtest completed with {len(self.trades)} trades")
        return True

    def get_metrics(self) -> Dict:
        """
        Calculate backtest metrics.

        Returns:
            Dictionary with performance metrics
        """
        if not self.trades:
            return {
                'win_rate': 0,
                'profit_factor': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'total_trades': 0,
                'total_return': 0,
                'total_return_percent': 0,
                'avg_trade_pnl': 0,
                'mae': 0,
                'mfe': 0,
            }

        # Win rate
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        win_rate = (len(winning_trades) / len(self.trades) * 100) if self.trades else 0

        # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades) if winning_trades else 0
        gross_loss = abs(sum(t.pnl for t in losing_trades)) if losing_trades else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (1 if gross_profit > 0 else 0)

        # Max drawdown
        equity = np.array(self.equity_curve)
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max
        max_drawdown = abs(np.min(drawdown)) * 100 if len(drawdown) > 0 else 0

        # Sharpe ratio (using log returns)
        if len(equity) > 1:
            log_returns = np.diff(np.log(equity))
            mean_return = np.mean(log_returns)
            std_return = np.std(log_returns)
            risk_free_rate = 0.0  # Assuming 0% risk-free rate
            sharpe = ((mean_return - risk_free_rate) / std_return * np.sqrt(252)) if std_return > 0 else 0
        else:
            sharpe = 0

        # Average trade P&L
        avg_trade_pnl = (sum(t.pnl for t in self.trades) / len(self.trades)) if self.trades else 0

        # MAE (Maximum Adverse Excursion) and MFE (Maximum Favorable Excursion)
        mae = 0
        mfe = 0
        if self.trades:
            for trade in self.trades:
                if trade.side == 'LONG':
                    # For long trades: MAE is how much it goes against us, MFE is how much it goes for us
                    mae = min(mae, trade.entry_price - trade.exit_price) if trade.exit_price else mae
                    mfe = max(mfe, trade.exit_price - trade.entry_price) if trade.exit_price else mfe
            mae = abs(mae)

        # Total return
        total_return = self.bankroll - self.initial_bankroll
        total_return_percent = (total_return / self.initial_bankroll * 100) if self.initial_bankroll > 0 else 0

        return {
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'total_trades': len(self.trades),
            'total_return': total_return,
            'total_return_percent': total_return_percent,
            'avg_trade_pnl': avg_trade_pnl,
            'mae': mae,
            'mfe': mfe,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
        }
