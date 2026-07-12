"""
Risk Management System for Kalshi Bitcoin Trading Bot

Enforces:
- Daily loss limits
- Position size constraints
- Maximum open positions
- Market concentration limits
- Minimum edge threshold (Bayesian adaptive)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple, Optional, List

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Risk management configuration"""
    MAX_DAILY_LOSS: float  # e.g., 500 USD
    MAX_POSITION_SIZE: float  # e.g., 10000 USD per position
    MAX_OPEN_POSITIONS: int  # e.g., 5
    MAX_CONCENTRATION: float  # e.g., 0.40 (40% of bankroll in correlated markets)
    MIN_EDGE_THRESHOLD: float  # e.g., 0.02 (2% minimum edge)
    BANKROLL: float  # Total trading capital
    CORRELATED_MARKETS: List[str]  # Markets considered correlated (e.g., all BTC contracts)


class RiskManager:
    """
    Enforces risk constraints and manages adaptive thresholds based on recent performance.
    Uses Bayesian updating: if recent trades underperform, tighten thresholds temporarily.
    """

    def __init__(self, config: RiskConfig, position_tracker):
        """
        Initialize risk manager.

        Args:
            config: RiskConfig instance with limits
            position_tracker: PositionTracker instance for accessing position/P&L data
        """
        self.config = config
        self.position_tracker = position_tracker

        # Daily tracking
        self.daily_realized_pnl = 0.0
        self.daily_unrealized_pnl = 0.0
        self.daily_trading_stopped = False
        self.day_start_time = datetime.utcnow()

        # Bayesian adaptive thresholds
        self.base_min_edge = config.MIN_EDGE_THRESHOLD
        self.current_min_edge = config.MIN_EDGE_THRESHOLD
        self.recent_trade_count = 0
        self.recent_win_rate = 0.5  # Start at 50%
        self.last_threshold_update = datetime.utcnow()

        logger.info(
            f"RiskManager initialized with config: daily_loss_limit={config.MAX_DAILY_LOSS}, "
            f"max_position_size={config.MAX_POSITION_SIZE}, max_open={config.MAX_OPEN_POSITIONS}, "
            f"min_edge={config.MIN_EDGE_THRESHOLD}"
        )

    def can_trade(self, signal: dict) -> Tuple[bool, str]:
        """
        Check if a signal is allowed under current risk constraints.

        Args:
            signal: dict with keys:
                - ticker: market ticker
                - side: 'BUY' or 'SELL'
                - price: limit price
                - count: number of contracts
                - expected_value: EV or win rate (for edge calculation)

        Returns:
            (allowed: bool, reason: str)
        """
        # Check 1: Daily loss limit
        if self.daily_trading_stopped:
            return False, "Daily loss limit reached; trading stopped for today"

        total_daily_loss = self.daily_realized_pnl + self.daily_unrealized_pnl
        if total_daily_loss <= -self.config.MAX_DAILY_LOSS:
            self.daily_trading_stopped = True
            logger.warning(
                f"Daily loss limit hit: {total_daily_loss:.2f} <= -{self.config.MAX_DAILY_LOSS}. "
                "Stopping trading for today."
            )
            return False, "Daily loss limit reached"

        # Check 2: Minimum edge threshold (adaptive)
        signal_edge = signal.get("expected_value", 0)
        if signal_edge < self.current_min_edge:
            reason = (
                f"Signal edge {signal_edge:.4f} below min threshold {self.current_min_edge:.4f}"
            )
            logger.debug(reason)
            return False, reason

        # Check 3: Max open positions
        open_positions = self.position_tracker.positions
        if len(open_positions) >= self.config.MAX_OPEN_POSITIONS:
            reason = f"Max open positions ({self.config.MAX_OPEN_POSITIONS}) reached"
            logger.debug(reason)
            return False, reason

        # Check 4: Position size limit
        trade_value = signal["count"] * signal["price"]
        if trade_value > self.config.MAX_POSITION_SIZE:
            reason = f"Trade value {trade_value:.2f} exceeds max position size {self.config.MAX_POSITION_SIZE}"
            logger.debug(reason)
            return False, reason

        # Check 5: Market concentration limit
        ticker = signal["ticker"]
        concentration_check = self._check_concentration(ticker, trade_value)
        if not concentration_check[0]:
            return False, concentration_check[1]

        # Check 6: Duplicate order prevention
        existing_order = self._check_existing_position(ticker, signal["side"])
        if existing_order:
            reason = f"Position already exists for {ticker} {signal['side']}"
            logger.debug(reason)
            return False, reason

        logger.info(
            f"Signal allowed for {ticker}: side={signal['side']}, edge={signal_edge:.4f}, "
            f"size={signal['count']} @ {signal['price']}"
        )
        return True, "OK"

    def update_pnl(self, fill: dict) -> None:
        """
        Update daily P&L tracking after a fill.

        Args:
            fill: dict with keys:
                - ticker: market ticker
                - side: 'BUY' or 'SELL'
                - count: number of contracts filled
                - price: fill price
                - pnl: realized P&L from this fill (optional, estimated if not provided)
        """
        fill_pnl = fill.get("pnl", 0)
        self.daily_realized_pnl += fill_pnl

        ticker = fill.get("ticker", "UNKNOWN")
        logger.info(
            f"PnL updated: fill_pnl={fill_pnl:.2f}, daily_realized={self.daily_realized_pnl:.2f}, "
            f"daily_unrealized={self.daily_unrealized_pnl:.2f}, total={self.daily_realized_pnl + self.daily_unrealized_pnl:.2f}"
        )

        # Update Bayesian metrics
        self._update_bayesian_metrics(fill)

    def reset_daily(self) -> None:
        """
        Reset daily P&L tracking at start of day.
        Called at market open or start of each trading session.
        """
        self.daily_realized_pnl = 0.0
        self.daily_unrealized_pnl = 0.0
        self.daily_trading_stopped = False
        self.day_start_time = datetime.utcnow()

        # Optionally reset adaptive thresholds
        self.current_min_edge = self.base_min_edge
        logger.info("Daily risk state reset. Trading stopped flag cleared.")

    def set_unrealized_pnl(self, unrealized_pnl: float) -> None:
        """Update unrealized P&L for risk calculations."""
        self.daily_unrealized_pnl = unrealized_pnl

    # --- Private Methods ---

    def _check_concentration(self, ticker: str, trade_value: float) -> Tuple[bool, str]:
        """
        Check if adding this trade would exceed concentration limits.
        Assumes all BTC markets are correlated.

        Returns:
            (allowed: bool, reason: str)
        """
        correlated_markets = getattr(self.config, "CORRELATED_MARKETS", [])
        if not correlated_markets or ticker not in correlated_markets:
            # No correlated markets configured, or this ticker isn't in the list
            return True, ""

        # Calculate current concentration in correlated markets
        open_positions = list(self.position_tracker.positions.values())
        correlated_value = sum(
            p.entry_price * p.quantity
            for p in open_positions
            if p.ticker in correlated_markets
        )
        correlated_value += trade_value

        max_correlated_value = self.config.BANKROLL * self.config.MAX_CONCENTRATION
        if correlated_value > max_correlated_value:
            reason = (
                f"Correlated concentration {correlated_value:.2f} would exceed "
                f"limit {max_correlated_value:.2f}"
            )
            return False, reason

        return True, ""

    def _check_existing_position(self, ticker: str, side: str) -> Optional[dict]:
        """Check if a position already exists for this ticker+side."""
        position = self.position_tracker.get_position(ticker)
        if position:
            # If same side, we have a duplicate
            if position.side == side:
                return position
        return None

    def _update_bayesian_metrics(self, fill: dict) -> None:
        """
        Update Bayesian performance metrics to adapt thresholds.
        If win rate < 50%, gradually increase MIN_EDGE_THRESHOLD.
        """
        pnl = fill.get("pnl", 0)
        self.recent_trade_count += 1

        # Simple moving average of win rate
        is_win = 1.0 if pnl > 0 else 0.0
        self.recent_win_rate = (
            0.9 * self.recent_win_rate + 0.1 * is_win
        )

        # Every 10 trades, update threshold
        if self.recent_trade_count % 10 == 0:
            if self.recent_win_rate < 0.5:
                # Recent performance below 50%, increase edge requirement
                multiplier = 1.0 + (0.5 - self.recent_win_rate) * 0.5
                self.current_min_edge = self.base_min_edge * multiplier
                logger.warning(
                    f"Bayesian update: win_rate={self.recent_win_rate:.2%}, "
                    f"increased min_edge to {self.current_min_edge:.4f}"
                )
            else:
                # Performance OK, relax threshold back to base
                self.current_min_edge = self.base_min_edge
                logger.info(
                    f"Bayesian update: win_rate={self.recent_win_rate:.2%}, "
                    f"reset min_edge to {self.current_min_edge:.4f}"
                )

            self.last_threshold_update = datetime.utcnow()

    def get_metrics(self) -> dict:
        """Get current risk metrics for logging/monitoring."""
        return {
            "daily_realized_pnl": self.daily_realized_pnl,
            "daily_unrealized_pnl": self.daily_unrealized_pnl,
            "daily_total_pnl": self.daily_realized_pnl + self.daily_unrealized_pnl,
            "daily_trading_stopped": self.daily_trading_stopped,
            "current_min_edge": self.current_min_edge,
            "recent_win_rate": self.recent_win_rate,
            "open_positions_count": len(self.position_tracker.positions),
        }
