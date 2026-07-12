"""
Mean reversion trading strategy for price bracket contracts.

Identifies overbought/oversold conditions and trades when price deviates
significantly from fair value (estimated probability).
Works well on KXBTCD daily and KXBTC price bracket contracts.
"""

import logging
from typing import Optional, Dict, Any
import pandas as pd
import ta
import numpy as np

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion strategy using RSI, Bollinger Bands, and VWAP.

    Trades when market price deviates significantly from fair value,
    expecting reversion back to mean.
    """

    def __init__(self, name: str = "mean_reversion", settings: Optional[Dict[str, Any]] = None):
        """
        Initialize mean reversion strategy.

        Args:
            name: Strategy name
            settings: Strategy parameters including:
                - rsi_period: RSI period (default 14)
                - rsi_oversold: RSI oversold threshold (default 30)
                - rsi_overbought: RSI overbought threshold (default 70)
                - bb_period: Bollinger Band period (default 20)
                - bb_std: Bollinger Band std dev (default 2)
                - fair_value_threshold: Price deviation threshold (default 0.5)
                - min_edge: Minimum EV to take trade (default 0.03)
                - min_candles: Minimum candles required (default 30)
        """
        if settings is None:
            settings = {}

        # Set defaults
        settings.setdefault('rsi_period', 14)
        settings.setdefault('rsi_oversold', 30)
        settings.setdefault('rsi_overbought', 70)
        settings.setdefault('bb_period', 20)
        settings.setdefault('bb_std', 2.0)
        settings.setdefault('fair_value_threshold', 0.5)
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
        Analyze market for mean reversion opportunities.

        Args:
            market: Market data with current price
            orderbook: Order book data
            trades: Recent trade list
            candles: OHLCV candle data
            ticker: Market ticker (passed by trader, unused here)
            recent_trades: Alias for trades (passed by trader)

        Returns:
            Signal if valid mean reversion opportunity detected, None otherwise
        """
        try:
            # Accept either parameter name
            if candles is None:
                candles = trades or recent_trades or []

            # Validate inputs
            if not candles or len(candles) < self.settings['min_candles']:
                logger.debug(f"Insufficient candles: {len(candles) if candles else 0}")
                return None

            # Build price and volume series
            closes = pd.Series([c['close'] for c in candles], name='close')
            highs = pd.Series([c.get('high', c['close']) for c in candles], name='high')
            lows = pd.Series([c.get('low', c['close']) for c in candles], name='low')
            volumes = pd.Series([c.get('volume', 0) for c in candles], name='volume')

            if closes.empty or len(closes) < self.settings['min_candles']:
                return None

            # Calculate indicators
            rsi = self._calculate_rsi(closes)
            if rsi is None or rsi.empty:
                return None

            bb_result = self._calculate_bollinger_bands(closes)
            if bb_result is None:
                return None

            bb_upper, bb_middle, bb_lower = bb_result

            vwap = self._calculate_vwap(highs, lows, closes, volumes)

            # Get current market price
            current_price = market.get('last_price', 0.5)
            if current_price <= 0 or current_price >= 1:
                logger.warning(f"Invalid market price: {current_price}")
                return None

            # Estimate fair value
            fair_value = self._estimate_fair_value(closes, vwap, rsi)

            # Detect mean reversion opportunity
            signal_direction, confidence = self._detect_mean_reversion(
                current_price, fair_value, rsi, bb_upper, bb_lower
            )

            if signal_direction is None:
                logger.debug("No mean reversion signal detected")
                return None

            # Calculate model probability
            model_prob = self._calculate_model_probability(
                signal_direction, current_price, fair_value, rsi, confidence
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
            reasoning = (
                f"Price {current_price:.3f} deviating from fair value {fair_value:.3f}. "
                f"RSI: {rsi.iloc[-1]:.1f}, Confidence: {confidence:.2f}, EV: {ev:.4f}"
            )

            return Signal(
                direction="BUY" if signal_direction == 1 else "SELL",
                strategy_name=self.name,
                model_probability=model_prob,
                confidence=confidence,
                position_size_usd=position_size,
                entry_price=current_price,
                reasoning=reasoning,
                metadata={
                    'fair_value': fair_value,
                    'rsi_value': float(rsi.iloc[-1]),
                    'bb_upper': float(bb_upper.iloc[-1]),
                    'bb_lower': float(bb_lower.iloc[-1]),
                    'deviation_pct': abs(current_price - fair_value) / fair_value * 100,
                }
            )

        except Exception as e:
            logger.error(f"Error in mean reversion analyze: {e}", exc_info=True)
            return None

    def should_exit(
        self,
        position: Dict[str, Any],
        market: Dict[str, Any],
        orderbook: Dict[str, Any]
    ) -> bool:
        """
        Determine exit conditions for mean reversion strategy.

        Exit if:
        - Price reverts toward fair value (>= 90% of fair value)
        - Contract approaching close time (< 1 minute)
        - Maximum hold time exceeded

        Args:
            position: Current position data
            market: Current market data
            orderbook: Current order book

        Returns:
            True if should exit, False otherwise
        """
        try:
            current_price = market.get('last_price', 0.5)
            fair_value = position.get('metadata', {}).get('fair_value', 0.5)
            position_direction = position.get('direction', 'BUY')

            # Check if contract is about to close
            time_to_close = market.get('time_to_close_seconds', 0)
            if time_to_close < 60:
                logger.info(f"Exiting - contract closing in {time_to_close}s")
                return True

            # Exit when price reverts toward fair value
            if position_direction == 'BUY':
                # Bought when price was below fair value, exit when it reverts up
                if current_price >= fair_value * 0.9:
                    logger.info(f"Exiting BUY - price reverted to {current_price:.3f}")
                    return True
            else:  # SELL
                # Sold when price was above fair value, exit when it reverts down
                if current_price <= fair_value * 1.1:
                    logger.info(f"Exiting SELL - price reverted to {current_price:.3f}")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error in mean reversion should_exit: {e}")
            return False

    def check_exit(self, position) -> Optional[dict]:
        """Compatibility shim called by trader.py."""
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

    def _calculate_bollinger_bands(self, closes: pd.Series) -> Optional[tuple]:
        """
        Calculate Bollinger Bands.

        Returns:
            Tuple of (bb_upper, bb_middle, bb_lower) or None if error
        """
        try:
            bb_indicator = ta.volatility.BollingerBands(
                closes,
                window=self.settings['bb_period'],
                window_dev=self.settings['bb_std']
            )
            bb_upper = bb_indicator.bollinger_hband()
            bb_middle = bb_indicator.bollinger_mavg()
            bb_lower = bb_indicator.bollinger_lband()

            if bb_upper is None or bb_middle is None or bb_lower is None:
                return None

            return bb_upper, bb_middle, bb_lower
        except Exception as e:
            logger.error(f"Error calculating Bollinger Bands: {e}")
            return None

    def _calculate_vwap(
        self,
        highs: pd.Series,
        lows: pd.Series,
        closes: pd.Series,
        volumes: pd.Series
    ) -> Optional[pd.Series]:
        """
        Calculate Volume Weighted Average Price.

        Returns:
            VWAP series or None if error
        """
        try:
            # Manual VWAP calculation: (close * volume).cumsum() / volume.cumsum()
            vwap = (closes * volumes).cumsum() / volumes.cumsum()
            return vwap
        except Exception as e:
            logger.error(f"Error calculating VWAP: {e}")
            return None

    def _estimate_fair_value(
        self,
        closes: pd.Series,
        vwap: Optional[pd.Series],
        rsi: pd.Series
    ) -> float:
        """
        Estimate fair value for the contract.

        Fair value represents the implied probability/price level.
        Uses VWAP, recent close, and RSI-adjusted mean.

        Returns:
            Estimated fair value (0-1)
        """
        try:
            recent_close = closes.iloc[-1]

            # Start with recent close
            fair_value = recent_close

            # Adjust with VWAP if available
            if vwap is not None and not vwap.empty:
                vwap_value = vwap.iloc[-1]
                fair_value = 0.6 * recent_close + 0.4 * vwap_value

            # Ensure fair value is in valid range
            fair_value = max(0.05, min(0.95, fair_value))

            return fair_value

        except Exception as e:
            logger.error(f"Error estimating fair value: {e}")
            return 0.5

    def _detect_mean_reversion(
        self,
        current_price: float,
        fair_value: float,
        rsi: pd.Series,
        bb_upper: pd.Series,
        bb_lower: pd.Series
    ) -> tuple:
        """
        Detect mean reversion opportunity.

        Returns:
            Tuple of (direction: 1 for buy, -1 for sell, None for no signal, confidence: 0-1)
        """
        try:
            current_rsi = rsi.iloc[-1]
            current_bb_upper = bb_upper.iloc[-1]
            current_bb_lower = bb_lower.iloc[-1]

            deviation_threshold = self.settings['fair_value_threshold']
            deviation_pct = abs(current_price - fair_value) / fair_value

            # Price too far below fair value + RSI oversold = BUY
            if (current_price <= fair_value * (1 - deviation_threshold / 100) and
                    current_rsi < self.settings['rsi_oversold']):

                # Confidence increases with larger deviation and more extreme RSI
                dev_confidence = min(1.0, deviation_pct / (deviation_threshold / 100))
                rsi_confidence = max(0, (self.settings['rsi_oversold'] - current_rsi) / 30)
                confidence = 0.5 + 0.25 * dev_confidence + 0.25 * rsi_confidence

                return 1, confidence

            # Price too far above fair value + RSI overbought = SELL
            elif (current_price >= fair_value * (1 + deviation_threshold / 100) and
                  current_rsi > self.settings['rsi_overbought']):

                # Confidence increases with larger deviation and more extreme RSI
                dev_confidence = min(1.0, (current_price - fair_value) / (fair_value * deviation_threshold / 100))
                rsi_confidence = max(0, (current_rsi - self.settings['rsi_overbought']) / 30)
                confidence = 0.5 + 0.25 * dev_confidence + 0.25 * rsi_confidence

                return -1, confidence

            return None, 0.0

        except Exception as e:
            logger.error(f"Error detecting mean reversion: {e}")
            return None, 0.0

    def _calculate_model_probability(
        self,
        direction: int,
        current_price: float,
        fair_value: float,
        rsi: pd.Series,
        confidence: float
    ) -> float:
        """
        Calculate model probability based on mean reversion parameters.

        Args:
            direction: Signal direction (1 for buy, -1 for sell)
            current_price: Current market price
            fair_value: Estimated fair value
            rsi: RSI series
            confidence: Signal confidence (0-1)

        Returns:
            Estimated probability of reversion (0.5-1.0 or 0.0-0.5)
        """
        try:
            # Base probability from confidence
            base_prob = 0.5 + (confidence * 0.25)

            # Adjust based on how extreme the deviation is
            price_diff = abs(current_price - fair_value)
            deviation_factor = min(0.2, price_diff / fair_value)
            base_prob += deviation_factor * 0.15

            # Adjust based on RSI extremeness
            current_rsi = rsi.iloc[-1]
            if direction == 1:  # BUY
                # More extreme oversold = higher probability of reversion
                rsi_factor = max(0, (30 - current_rsi) / 30) * 0.1
                base_prob += rsi_factor
            else:  # SELL
                # More extreme overbought = higher probability of reversion
                rsi_factor = max(0, (current_rsi - 70) / 30) * 0.1
                base_prob += rsi_factor

            return min(0.95, max(0.05, base_prob))

        except Exception as e:
            logger.error(f"Error calculating model probability: {e}")
            return 0.5
