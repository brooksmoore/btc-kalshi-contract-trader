"""
Momentum trading strategy for KXBTC15M contracts (15-minute BTC up/down).

Uses MACD, RSI, and volume analysis to identify momentum shifts.
Best suited for short-term intraday trading on 15-minute intervals.
"""

import logging
from typing import Optional, Dict, Any
import pandas as pd
import ta
import numpy as np

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class MomentumStrategy(BaseStrategy):
    """
    Momentum strategy using MACD, RSI, and volume indicators.

    Generates signals when multiple momentum indicators align and
    the expected value exceeds the minimum edge threshold.
    """

    def __init__(self, name: str = "momentum", settings: Optional[Dict[str, Any]] = None):
        """
        Initialize momentum strategy.

        Args:
            name: Strategy name
            settings: Strategy parameters including:
                - macd_fast: MACD fast period (default 3)
                - macd_slow: MACD slow period (default 15)
                - macd_signal: MACD signal period (default 3)
                - rsi_period: RSI period (default 14)
                - min_signal_strength: Minimum combined signal strength (default 0.6)
                - min_candles: Minimum candles required for analysis (default 30)
        """
        if settings is None:
            settings = {}

        # Set defaults
        settings.setdefault('macd_fast', 3)
        settings.setdefault('macd_slow', 15)
        settings.setdefault('macd_signal', 3)
        settings.setdefault('rsi_period', 14)
        settings.setdefault('min_signal_strength', 0.6)
        settings.setdefault('min_candles', 30)
        settings.setdefault('kelly_fraction', 0.25)
        settings.setdefault('max_position_size', 1000)
        settings.setdefault('min_edge', 0.02)

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
        Analyze market data using momentum indicators.

        Args:
            market: Market data with current price
            orderbook: Order book data
            trades: Recent trade list
            candles: OHLCV candle data
            ticker: Market ticker (passed by trader, unused here)
            recent_trades: Alias for trades (passed by trader)

        Returns:
            Signal if valid momentum signal detected, None otherwise
        """
        try:
            # Accept either parameter name
            if candles is None:
                candles = trades or recent_trades or []

            # Validate inputs
            if not candles or len(candles) < self.settings['min_candles']:
                logger.debug(f"Insufficient candles: {len(candles) if candles else 0}")
                return None

            # Build price series from candles
            closes = pd.Series([c['close'] for c in candles], name='close')
            volumes = pd.Series([c.get('volume', 0) for c in candles], name='volume')

            if closes.empty:
                return None

            # Calculate indicators
            macd_result = self._calculate_macd(closes)
            if macd_result is None:
                return None

            macd_line, signal_line, histogram = macd_result

            rsi = self._calculate_rsi(closes)
            if rsi is None or rsi.empty:
                return None

            obv = self._calculate_obv(closes, volumes)

            # Generate signals
            macd_signal = self._get_macd_signal(macd_line, signal_line, histogram)
            rsi_signal = self._get_rsi_signal(rsi)
            volume_signal = self._get_volume_signal(obv)

            # Combine signals
            combined_signal, signal_strength = self._combine_signals(
                macd_signal, rsi_signal, volume_signal
            )

            if combined_signal is None or signal_strength < self.settings['min_signal_strength']:
                logger.debug(f"Signal strength {signal_strength} below threshold")
                return None

            # Calculate model probability based on signal strength and alignment
            model_prob = self._calculate_model_probability(
                signal_strength, macd_signal, rsi_signal, volume_signal
            )

            # Get current market price
            current_price = market.get('last_price', 0.5)
            if current_price <= 0 or current_price >= 1:
                logger.warning(f"Invalid market price: {current_price}")
                return None

            # Calculate EV
            ev = self.calculate_ev(model_prob, current_price)
            if ev < self.settings['min_edge']:
                logger.debug(f"EV {ev:.4f} below minimum edge {self.settings['min_edge']}")
                return None

            # Calculate position size
            kelly_pct = self.calculate_kelly(model_prob, current_price)
            position_size = self.calculate_position_size(kelly_pct, market.get('bankroll', 1000))

            # Build reasoning
            reasoning = (
                f"MACD {macd_signal}, RSI {rsi_signal}, Volume {volume_signal}. "
                f"Signal strength: {signal_strength:.2f}, Model prob: {model_prob:.2f}, EV: {ev:.4f}"
            )

            return Signal(
                direction="BUY" if combined_signal == 1 else "SELL",
                strategy_name=self.name,
                model_probability=model_prob,
                confidence=signal_strength,
                position_size_usd=position_size,
                entry_price=current_price,
                reasoning=reasoning,
                metadata={
                    'macd_signal': macd_signal,
                    'rsi_signal': rsi_signal,
                    'volume_signal': volume_signal,
                    'macd_value': float(macd_line.iloc[-1]) if not macd_line.empty else 0,
                    'rsi_value': float(rsi.iloc[-1]) if not rsi.empty else 0,
                }
            )

        except Exception as e:
            logger.error(f"Error in momentum analyze: {e}", exc_info=True)
            return None

    def should_exit(
        self,
        position: Dict[str, Any],
        market: Dict[str, Any],
        orderbook: Dict[str, Any]
    ) -> bool:
        """
        Determine exit conditions for momentum strategy.

        Exit if:
        - Reverse signal detected
        - Take-profit at 90% of model probability
        - Contract approaching close time (< 1 minute)

        Args:
            position: Current position data
            market: Current market data
            orderbook: Current order book

        Returns:
            True if should exit, False otherwise
        """
        try:
            current_price = market.get('last_price', 0.5)
            position_direction = position.get('direction', 'BUY')
            entry_price = position.get('entry_price', 0.5)
            model_prob = position.get('model_probability', 0.5)

            # Check if contract is about to close (< 1 minute remaining)
            time_to_close = market.get('time_to_close_seconds', 0)
            if time_to_close < 60:
                logger.info(f"Exiting - contract closing in {time_to_close}s")
                return True

            # Take profit at 90% of model probability
            if position_direction == 'BUY':
                if current_price >= model_prob * 0.9:
                    logger.info(f"Exiting BUY - take profit at {current_price:.3f}")
                    return True
            else:  # SELL
                if current_price <= (1 - model_prob) * 0.9:
                    logger.info(f"Exiting SELL - take profit at {current_price:.3f}")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error in momentum should_exit: {e}")
            return False

    def check_exit(self, position) -> Optional[dict]:
        """Compatibility shim called by trader.py."""
        return None

    def _calculate_macd(self, closes: pd.Series) -> Optional[tuple]:
        """
        Calculate MACD indicator.

        Returns:
            Tuple of (macd_line, signal_line, histogram) or None if error
        """
        try:
            macd_indicator = ta.trend.MACD(
                closes,
                window_fast=self.settings['macd_fast'],
                window_slow=self.settings['macd_slow'],
                window_sign=self.settings['macd_signal']
            )
            macd_line = macd_indicator.macd()
            signal_line = macd_indicator.macd_signal()
            histogram = macd_indicator.macd_diff()

            if macd_line is None or signal_line is None or histogram is None:
                return None

            return macd_line, signal_line, histogram
        except Exception as e:
            logger.error(f"Error calculating MACD: {e}")
            return None

    def _calculate_rsi(self, closes: pd.Series) -> Optional[pd.Series]:
        """
        Calculate RSI indicator.

        Returns:
            RSI series or None if error
        """
        try:
            rsi_indicator = ta.momentum.RSIIndicator(closes, window=self.settings['rsi_period'])
            rsi = rsi_indicator.rsi()
            return rsi
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}")
            return None

    def _calculate_obv(self, closes: pd.Series, volumes: pd.Series) -> Optional[pd.Series]:
        """
        Calculate On-Balance Volume.

        Returns:
            OBV series or None if error
        """
        try:
            obv_indicator = ta.volume.OnBalanceVolumeIndicator(closes, volumes)
            obv = obv_indicator.on_balance_volume()
            return obv
        except Exception as e:
            logger.error(f"Error calculating OBV: {e}")
            return None

    def _get_macd_signal(self, macd_line: pd.Series, signal_line: pd.Series, histogram: pd.Series) -> Optional[int]:
        """
        Generate MACD signal from MACD values.

        Returns:
            1 for bullish (MACD > signal and positive histogram),
            -1 for bearish (MACD < signal and negative histogram),
            0 for no clear signal
        """
        try:
            if macd_line.empty or signal_line.empty or histogram.empty:
                return 0

            current_macd = macd_line.iloc[-1]
            current_signal = signal_line.iloc[-1]
            current_histogram = histogram.iloc[-1]

            # Check for crossover or divergence
            if current_macd > current_signal and current_histogram > 0:
                return 1  # Bullish
            elif current_macd < current_signal and current_histogram < 0:
                return -1  # Bearish
            else:
                return 0

        except Exception as e:
            logger.error(f"Error in MACD signal: {e}")
            return 0

    def _get_rsi_signal(self, rsi: pd.Series) -> int:
        """
        Generate RSI signal based on overbought/oversold levels.

        Returns:
            1 for potential bullish (RSI < 50 and trending up),
            -1 for potential bearish (RSI > 50 and trending down),
            0 for neutral
        """
        try:
            if rsi.empty or len(rsi) < 2:
                return 0

            current_rsi = rsi.iloc[-1]
            prev_rsi = rsi.iloc[-2]

            # Trending up in lower half (potential upside)
            if current_rsi < 50 and current_rsi > prev_rsi:
                return 1

            # Trending down in upper half (potential downside)
            elif current_rsi > 50 and current_rsi < prev_rsi:
                return -1

            return 0

        except Exception as e:
            logger.error(f"Error in RSI signal: {e}")
            return 0

    def _get_volume_signal(self, obv: Optional[pd.Series]) -> int:
        """
        Generate volume signal based on OBV trend.

        Returns:
            1 for bullish volume,
            -1 for bearish volume,
            0 for neutral
        """
        try:
            if obv is None or obv.empty or len(obv) < 5:
                return 0

            # Check if OBV is trending up or down
            recent_obv = obv.iloc[-5:]
            obv_trend = recent_obv.iloc[-1] - recent_obv.iloc[0]

            if obv_trend > 0:
                return 1
            elif obv_trend < 0:
                return -1
            else:
                return 0

        except Exception as e:
            logger.error(f"Error in volume signal: {e}")
            return 0

    def _combine_signals(self, macd: int, rsi: int, volume: int) -> tuple:
        """
        Combine individual signals into a unified direction and strength.

        Returns:
            Tuple of (direction: 1 for buy, -1 for sell, or None, strength: 0-1)
        """
        signals = [macd, rsi, volume]
        valid_signals = [s for s in signals if s != 0]

        if not valid_signals:
            return None, 0.0

        # Check if signals agree
        if all(s > 0 for s in valid_signals):
            strength = len(valid_signals) / 3.0
            return 1, strength
        elif all(s < 0 for s in valid_signals):
            strength = len(valid_signals) / 3.0
            return -1, strength
        else:
            # Mixed signals - return strength based on unanimity
            strength = len(valid_signals) / 6.0
            return None, strength

    def _calculate_model_probability(
        self,
        signal_strength: float,
        macd_signal: int,
        rsi_signal: int,
        volume_signal: int
    ) -> float:
        """
        Calculate model probability based on signal alignment and strength.

        Args:
            signal_strength: Combined signal strength (0-1)
            macd_signal: MACD signal direction (-1, 0, 1)
            rsi_signal: RSI signal direction (-1, 0, 1)
            volume_signal: Volume signal direction (-1, 0, 1)

        Returns:
            Estimated probability of the signaled direction (0.5-1.0 or 0.0-0.5)
        """
        # Base probability from signal strength
        base_prob = 0.5 + (signal_strength * 0.2)  # Up to 0.7

        # Bonus for all three signals agreeing
        signals = [macd_signal, rsi_signal, volume_signal]
        valid_signals = [s for s in signals if s != 0]

        if len(valid_signals) == 3:
            base_prob += 0.15  # Up to 0.85 if all three agree

        return min(0.95, max(0.05, base_prob))
