"""
Cumulative Volume Delta (CVD) divergence strategy for detecting reversals.

Identifies price-CVD divergences indicating potential trend reversals.
Particularly effective for catching turning points in BTC contracts.
"""

import logging
from typing import Optional, Dict, Any
import pandas as pd
import ta
import numpy as np

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class CVDDivergenceStrategy(BaseStrategy):
    """
    CVD divergence strategy for reversal detection.

    Detects when price and cumulative volume delta diverge (e.g., price
    falling but volume buying increasing), indicating potential reversals.
    """

    def __init__(self, name: str = "cvd_divergence", settings: Optional[Dict[str, Any]] = None):
        """
        Initialize CVD divergence strategy.

        Args:
            name: Strategy name
            settings: Strategy parameters including:
                - rsi_period: RSI period for confirmation (default 14)
                - cvd_lookback: Number of periods to analyze for divergence (default 20)
                - divergence_threshold: Minimum divergence to signal (default 0.3)
                - min_rsi_extreme: RSI must be more extreme than this for confirmation (default 40)
                - min_edge: Minimum EV to take trade (default 0.03)
                - min_candles: Minimum data points required (default 30)
        """
        if settings is None:
            settings = {}

        # Set defaults
        settings.setdefault('rsi_period', 14)
        settings.setdefault('cvd_lookback', 20)
        settings.setdefault('divergence_threshold', 0.3)
        settings.setdefault('min_rsi_extreme', 40)
        settings.setdefault('min_edge', 0.03)
        settings.setdefault('min_candles', 30)
        settings.setdefault('kelly_fraction', 0.25)
        settings.setdefault('max_position_size', 1000)

        super().__init__(name, settings)

    def analyze(
        self,
        market: Dict[str, Any],
        orderbook: Dict[str, Any],
        trades: list = None,
        candles: list = None,
        *,
        ticker: str = None,
        recent_trades: list = None,
    ) -> Optional[Signal]:
        """
        Analyze for CVD divergence signals.

        Args:
            market: Market data with current price
            orderbook: Order book data
            trades: Recent trade list
            candles: OHLCV candle data
            ticker: Market ticker (passed by trader, unused here)
            recent_trades: Alias for trades (passed by trader)

        Returns:
            Signal if valid CVD divergence detected, None otherwise
        """
        try:
            # Accept either parameter name
            if trades is None:
                trades = recent_trades or []
            if candles is None:
                candles = trades

            # Validate inputs
            if not trades or len(trades) < self.settings['min_candles']:
                logger.debug(f"Insufficient trades: {len(trades) if trades else 0}")
                return None

            if not candles or len(candles) < self.settings['min_candles']:
                logger.debug(f"Insufficient candles: {len(candles) if candles else 0}")
                return None

            # Calculate CVD from trades
            cvd = self._calculate_cvd_from_trades(trades)
            if cvd is None or len(cvd) < self.settings['min_candles']:
                logger.debug("Insufficient CVD data")
                return None

            # Build price series
            closes = pd.Series([c['close'] for c in candles], name='close')

            # Calculate RSI for confirmation
            rsi = self._calculate_rsi(closes)
            if rsi is None or rsi.empty:
                return None

            # Get current market price
            current_price = market.get('last_price', 0.5)
            if current_price <= 0 or current_price >= 1:
                logger.warning(f"Invalid market price: {current_price}")
                return None

            # Detect divergence
            divergence_type, divergence_strength = self._detect_divergence(
                closes, cvd
            )

            if divergence_type is None:
                logger.debug("No CVD divergence detected")
                return None

            # Confirm with RSI
            rsi_confirms = self._rsi_confirms_divergence(rsi, divergence_type)
            if not rsi_confirms:
                logger.debug(f"RSI does not confirm divergence type {divergence_type}")
                return None

            # Calculate model probability
            model_prob = self._calculate_model_probability(
                divergence_type, divergence_strength, rsi
            )

            # Calculate EV
            ev = self.calculate_ev(model_prob, current_price)
            if ev < self.settings['min_edge']:
                logger.debug(f"EV {ev:.4f} below minimum edge {self.settings['min_edge']:.4f}")
                return None

            # Calculate position size
            kelly_pct = self.calculate_kelly(model_prob, current_price)
            position_size = self.calculate_position_size(kelly_pct, market.get('bankroll', 1000))

            # Build reasoning
            div_name = "Bullish" if divergence_type == 1 else "Bearish"
            reasoning = (
                f"{div_name} divergence detected. Strength: {divergence_strength:.2f}, "
                f"RSI: {rsi.iloc[-1]:.1f}, Model prob: {model_prob:.2f}, EV: {ev:.4f}"
            )

            return Signal(
                direction="BUY" if divergence_type == 1 else "SELL",
                strategy_name=self.name,
                model_probability=model_prob,
                confidence=divergence_strength,
                position_size_usd=position_size,
                entry_price=current_price,
                reasoning=reasoning,
                metadata={
                    'divergence_type': "bullish" if divergence_type == 1 else "bearish",
                    'divergence_strength': divergence_strength,
                    'rsi_value': float(rsi.iloc[-1]),
                    'cvd_value': float(cvd.iloc[-1]),
                }
            )

        except Exception as e:
            logger.error(f"Error in CVD divergence analyze: {e}", exc_info=True)
            return None

    def should_exit(
        self,
        position: Dict[str, Any],
        market: Dict[str, Any],
        orderbook: Dict[str, Any]
    ) -> bool:
        """
        Determine exit conditions for CVD divergence strategy.

        Exit if:
        - Divergence resolves (price catches up to volume direction)
        - Time-based exit (position held > 30 minutes)
        - Contract approaching close time (< 1 minute)

        Args:
            position: Current position data
            market: Current market data
            orderbook: Current order book

        Returns:
            True if should exit, False otherwise
        """
        try:
            # Check if contract is about to close
            time_to_close = market.get('time_to_close_seconds', 0)
            if time_to_close < 60:
                logger.info(f"Exiting - contract closing in {time_to_close}s")
                return True

            # Check position hold time
            position_age_seconds = position.get('age_seconds', 0)
            if position_age_seconds > 1800:  # 30 minutes
                logger.info(f"Exiting - position held for {position_age_seconds}s")
                return True

            return False

        except Exception as e:
            logger.error(f"Error in CVD should_exit: {e}")
            return False

    def check_exit(self, position) -> Optional[dict]:
        """Compatibility shim called by trader.py."""
        return None

    def _calculate_cvd_from_trades(self, trades: list) -> Optional[pd.Series]:
        """
        Calculate Cumulative Volume Delta from trade list.

        Args:
            trades: List of trade dictionaries with 'price', 'size', 'side' keys

        Returns:
            CVD series or None if error
        """
        try:
            if not trades:
                return None

            cvd_values = []
            cumulative = 0

            for trade in trades:
                price = trade.get('price', 0)
                size = trade.get('size', 0)
                side = trade.get('side', 'buy').lower()

                if side in ['buy', 'long']:
                    cumulative += size
                else:
                    cumulative -= size

                cvd_values.append(cumulative)

            if not cvd_values:
                return None

            return pd.Series(cvd_values, name='cvd')

        except Exception as e:
            logger.error(f"Error calculating CVD: {e}")
            return None

    def _calculate_rsi(self, closes: pd.Series) -> Optional[pd.Series]:
        """Calculate RSI indicator."""
        try:
            rsi_indicator = ta.momentum.RSIIndicator(closes, window=self.settings['rsi_period'])
            rsi = rsi_indicator.rsi()
            return rsi
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}")
            return None

    def _detect_divergence(
        self,
        closes: pd.Series,
        cvd: pd.Series
    ) -> tuple:
        """
        Detect price-CVD divergence.

        Bullish divergence: Price making lower lows while CVD making higher lows
        Bearish divergence: Price making higher highs while CVD making lower highs

        Returns:
            Tuple of (divergence_type: 1 for bullish, -1 for bearish, None, strength: 0-1)
        """
        try:
            lookback = self.settings['cvd_lookback']

            if len(closes) < lookback or len(cvd) < lookback:
                return None, 0.0

            # Get recent data — reset_index so positional and label indices match
            recent_closes = closes.iloc[-lookback:].reset_index(drop=True)
            recent_cvd = cvd.iloc[-lookback:].reset_index(drop=True)

            # Find extremes in recent period (now idxmin/idxmax return 0-based positions)
            price_min_idx = recent_closes.idxmin()
            price_max_idx = recent_closes.idxmax()
            cvd_min_idx = recent_cvd.idxmin()
            cvd_max_idx = recent_cvd.idxmax()

            # Get values at these points
            price_min = recent_closes.iloc[price_min_idx]
            price_max = recent_closes.iloc[price_max_idx]
            cvd_min = recent_cvd.iloc[cvd_min_idx]
            cvd_max = recent_cvd.iloc[cvd_max_idx]

            current_price = closes.iloc[-1]
            current_cvd = cvd.iloc[-1]

            # Bullish divergence: lower price but higher volume conviction
            if price_min_idx < price_max_idx:  # Recently made lower low
                # Check if CVD is making higher low
                if cvd_min_idx < cvd_max_idx and cvd_max > cvd_min:
                    # Price still low but CVD rising
                    if current_price <= price_max * 1.05:  # Still near recent low
                        price_strength = 1.0 - (price_max - price_min) / price_max
                        cvd_strength = (cvd_max - cvd_min) / abs(cvd_max) if cvd_max != 0 else 0
                        strength = min(1.0, 0.5 * price_strength + 0.5 * cvd_strength)
                        return 1, strength

            # Bearish divergence: higher price but lower volume conviction
            if price_max_idx < price_min_idx:  # Recently made higher high
                # Check if CVD is making lower high
                if cvd_max_idx < cvd_min_idx and cvd_min < cvd_max:
                    # Price still high but CVD falling
                    if current_price >= price_min * 0.95:  # Still near recent high
                        price_strength = 1.0 - (price_max - price_min) / price_max
                        cvd_strength = (cvd_max - cvd_min) / abs(cvd_max) if cvd_max != 0 else 0
                        strength = min(1.0, 0.5 * price_strength + 0.5 * cvd_strength)
                        return -1, strength

            return None, 0.0

        except Exception as e:
            logger.error(f"Error detecting divergence: {e}")
            return None, 0.0

    def _rsi_confirms_divergence(self, rsi: pd.Series, divergence_type: int) -> bool:
        """
        Check if RSI confirms the divergence signal.

        Args:
            rsi: RSI series
            divergence_type: 1 for bullish, -1 for bearish

        Returns:
            True if RSI confirms, False otherwise
        """
        try:
            if rsi.empty:
                return False

            current_rsi = rsi.iloc[-1]
            min_extreme = self.settings['min_rsi_extreme']

            # Bullish divergence should have low RSI (oversold area)
            if divergence_type == 1:
                return current_rsi < min_extreme

            # Bearish divergence should have high RSI (overbought area)
            elif divergence_type == -1:
                return current_rsi > (100 - min_extreme)

            return False

        except Exception as e:
            logger.error(f"Error confirming with RSI: {e}")
            return False

    def _calculate_model_probability(
        self,
        divergence_type: int,
        divergence_strength: float,
        rsi: pd.Series
    ) -> float:
        """
        Calculate model probability based on divergence parameters.

        Args:
            divergence_type: 1 for bullish, -1 for bearish
            divergence_strength: Strength of the divergence (0-1)
            rsi: RSI series

        Returns:
            Estimated probability of the signaled direction (0.5-1.0 or 0.0-0.5)
        """
        try:
            # Base probability from divergence strength
            base_prob = 0.5 + (divergence_strength * 0.25)

            # Bonus for extreme RSI confirmation
            current_rsi = rsi.iloc[-1]

            if divergence_type == 1:  # Bullish
                # More oversold = higher probability
                if current_rsi < 30:
                    extreme_bonus = (30 - current_rsi) / 30 * 0.15
                    base_prob += extreme_bonus
            else:  # Bearish
                # More overbought = higher probability
                if current_rsi > 70:
                    extreme_bonus = (current_rsi - 70) / 30 * 0.15
                    base_prob += extreme_bonus

            return min(0.95, max(0.05, base_prob))

        except Exception as e:
            logger.error(f"Error calculating model probability: {e}")
            return 0.5
