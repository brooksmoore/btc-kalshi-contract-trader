"""
Ensemble strategy that combines signals from multiple sub-strategies.

Runs momentum, mean reversion, and CVD divergence strategies and weights
their signals to create a high-confidence composite signal.
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from strategies.base_strategy import BaseStrategy, Signal
from strategies.momentum_strategy import MomentumStrategy
from strategies.mean_reversion_strategy import MeanReversionStrategy
from strategies.cvd_divergence_strategy import CVDDivergenceStrategy

logger = logging.getLogger(__name__)


@dataclass
class StrategySignal:
    """Helper class to track individual strategy signals."""
    strategy: BaseStrategy
    signal: Optional[Signal]
    weight: float


class EnsembleStrategy(BaseStrategy):
    """
    Meta-strategy combining three sub-strategies.

    Weights signals from momentum, mean reversion, and CVD divergence
    strategies. Generates composite signals when 2+ strategies agree.
    Higher confidence when all three agree.
    """

    def __init__(self, name: str = "ensemble", settings: Optional[Dict[str, Any]] = None):
        """
        Initialize ensemble strategy.

        Args:
            name: Strategy name
            settings: Strategy parameters including:
                - momentum_weight: Weight for momentum strategy (default 0.35)
                - mean_reversion_weight: Weight for mean reversion (default 0.35)
                - cvd_weight: Weight for CVD divergence (default 0.30)
                - min_agreement: Minimum strategies that must agree (default 2)
                - min_composite_ev: Minimum composite EV (default 0.02)
                Plus settings for each sub-strategy
        """
        if settings is None:
            settings = {}

        # Set defaults for ensemble
        settings.setdefault('momentum_weight', 0.35)
        settings.setdefault('mean_reversion_weight', 0.35)
        settings.setdefault('cvd_weight', 0.30)
        settings.setdefault('min_agreement', 2)
        settings.setdefault('min_composite_ev', 0.02)
        settings.setdefault('kelly_fraction', 0.25)
        settings.setdefault('max_position_size', 1000)

        super().__init__(name, settings)

        # Initialize sub-strategies with shared settings
        self.momentum_strategy = MomentumStrategy("momentum", settings)
        self.mean_reversion_strategy = MeanReversionStrategy("mean_reversion", settings)
        self.cvd_strategy = CVDDivergenceStrategy("cvd_divergence", settings)

        # Define weight mapping
        self.strategy_weights = {
            "momentum": settings['momentum_weight'],
            "mean_reversion": settings['mean_reversion_weight'],
            "cvd_divergence": settings['cvd_weight'],
        }

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
        Run all sub-strategies and combine their signals.

        Args:
            market: Market data with current price
            orderbook: Order book data
            trades: Recent trade list
            candles: OHLCV candle data
            ticker: Market ticker (passed by trader, unused here)
            recent_trades: Alias for trades (passed by trader)

        Returns:
            Composite Signal if consensus reached, None otherwise
        """
        try:
            # Accept either parameter name
            if trades is None:
                trades = recent_trades or []
            if candles is None:
                candles = trades

            # Run all sub-strategies
            strategy_signals = [
                StrategySignal(
                    strategy=self.momentum_strategy,
                    signal=self.momentum_strategy.analyze(market, orderbook, trades, candles),
                    weight=self.strategy_weights["momentum"]
                ),
                StrategySignal(
                    strategy=self.mean_reversion_strategy,
                    signal=self.mean_reversion_strategy.analyze(market, orderbook, trades, candles),
                    weight=self.strategy_weights["mean_reversion"]
                ),
                StrategySignal(
                    strategy=self.cvd_strategy,
                    signal=self.cvd_strategy.analyze(market, orderbook, trades, candles),
                    weight=self.strategy_weights["cvd_divergence"]
                ),
            ]

            # Filter out None signals
            valid_signals = [s for s in strategy_signals if s.signal is not None]

            if not valid_signals:
                logger.debug("No valid signals from any sub-strategy")
                return None

            logger.info(f"Got signals from {len(valid_signals)}/3 strategies")

            # Check if minimum agreement is met
            min_agreement = self.settings['min_agreement']
            if len(valid_signals) < min_agreement:
                logger.debug(
                    f"Only {len(valid_signals)} strategies agree, need {min_agreement}"
                )
                return None

            # Check if all signals agree on direction
            directions = [s.signal.direction for s in valid_signals]
            if not self._all_same(directions):
                logger.debug(f"Signals disagree on direction: {directions}")
                return None

            # Combine signals
            composite_direction = valid_signals[0].signal.direction
            composite_model_prob = self._calculate_composite_probability(valid_signals)
            composite_confidence = self._calculate_composite_confidence(valid_signals)

            # Get current market price
            current_price = market.get('last_price', 0.5)
            if current_price <= 0 or current_price >= 1:
                logger.warning(f"Invalid market price: {current_price}")
                return None

            # Calculate composite EV
            composite_ev = self.calculate_ev(composite_model_prob, current_price)
            if composite_ev < self.settings['min_composite_ev']:
                logger.debug(
                    f"Composite EV {composite_ev:.4f} below threshold "
                    f"{self.settings['min_composite_ev']}"
                )
                return None

            # Calculate position size
            kelly_pct = self.calculate_kelly(composite_model_prob, current_price)
            position_size = self.calculate_position_size(
                kelly_pct, market.get('bankroll', 1000)
            )

            # Build composite reasoning
            strategy_names = [s.strategy.name for s in valid_signals]
            reasoning = (
                f"Ensemble consensus from {len(valid_signals)} strategies: {', '.join(strategy_names)}. "
                f"Composite prob: {composite_model_prob:.2f}, Confidence: {composite_confidence:.2f}, "
                f"EV: {composite_ev:.4f}"
            )

            # Build metadata with all sub-strategy signals
            metadata = {
                'num_strategies': len(valid_signals),
                'sub_signals': {s.strategy.name: s.signal.metadata for s in valid_signals},
                'strategy_probs': {s.strategy.name: s.signal.model_probability for s in valid_signals},
            }

            return Signal(
                direction=composite_direction,
                strategy_name=self.name,
                model_probability=composite_model_prob,
                confidence=composite_confidence,
                position_size_usd=position_size,
                entry_price=current_price,
                reasoning=reasoning,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Error in ensemble analyze: {e}", exc_info=True)
            return None

    def should_exit(
        self,
        position: Dict[str, Any],
        market: Dict[str, Any],
        orderbook: Dict[str, Any]
    ) -> bool:
        """
        Determine exit using consensus from sub-strategies.

        Exit if ANY sub-strategy votes to exit (conservative approach).

        Args:
            position: Current position data
            market: Current market data
            orderbook: Current order book

        Returns:
            True if any sub-strategy signals exit
        """
        try:
            exit_votes = [
                self.momentum_strategy.should_exit(position, market, orderbook),
                self.mean_reversion_strategy.should_exit(position, market, orderbook),
                self.cvd_strategy.should_exit(position, market, orderbook),
            ]

            # Exit if any strategy votes to exit (conservative)
            should_exit = any(exit_votes)

            if should_exit:
                exit_strategies = [
                    name for name, vote in zip(
                        ["momentum", "mean_reversion", "cvd"],
                        exit_votes
                    ) if vote
                ]
                logger.info(f"Exiting per signals from: {', '.join(exit_strategies)}")

            return should_exit

        except Exception as e:
            logger.error(f"Error in ensemble should_exit: {e}")
            return False

    def check_exit(self, position) -> Optional[dict]:
        """Compatibility shim called by trader.py."""
        return None

    def _all_same(self, items: list) -> bool:
        """Check if all items in list are the same."""
        if not items:
            return False
        return all(item == items[0] for item in items)

    def _calculate_composite_probability(
        self,
        strategy_signals: List[StrategySignal]
    ) -> float:
        """
        Calculate weighted composite probability.

        Args:
            strategy_signals: List of valid strategy signals

        Returns:
            Weighted average model probability
        """
        try:
            if not strategy_signals:
                return 0.5

            # Calculate weighted average
            total_weight = sum(s.weight for s in strategy_signals)
            if total_weight == 0:
                return 0.5

            weighted_prob = sum(
                s.signal.model_probability * s.weight
                for s in strategy_signals
            ) / total_weight

            # Boost probability if all three strategies agree
            if len(strategy_signals) == 3:
                # Add 0.05 bonus for unanimous agreement
                weighted_prob = min(0.95, weighted_prob + 0.05)

            return max(0.05, min(0.95, weighted_prob))

        except Exception as e:
            logger.error(f"Error calculating composite probability: {e}")
            return 0.5

    def _calculate_composite_confidence(
        self,
        strategy_signals: List[StrategySignal]
    ) -> float:
        """
        Calculate composite confidence score.

        Args:
            strategy_signals: List of valid strategy signals

        Returns:
            Composite confidence (0-1)
        """
        try:
            if not strategy_signals:
                return 0.0

            # Base confidence from average of individual confidences
            avg_confidence = sum(
                s.signal.confidence for s in strategy_signals
            ) / len(strategy_signals)

            # Bonus for multiple agreeing strategies
            agreement_bonus = 0.0
            if len(strategy_signals) == 2:
                agreement_bonus = 0.1
            elif len(strategy_signals) == 3:
                agreement_bonus = 0.25

            composite_confidence = min(1.0, avg_confidence + agreement_bonus)

            return composite_confidence

        except Exception as e:
            logger.error(f"Error calculating composite confidence: {e}")
            return 0.0

    def get_sub_strategy_details(
        self,
        market: Dict[str, Any],
        orderbook: Dict[str, Any],
        trades: list,
        candles: list
    ) -> Dict[str, Optional[Signal]]:
        """
        Get signals from all sub-strategies for debugging/monitoring.

        Args:
            market: Market data
            orderbook: Order book data
            trades: Trade list
            candles: Candle data

        Returns:
            Dictionary mapping strategy names to their signals
        """
        try:
            return {
                "momentum": self.momentum_strategy.analyze(market, orderbook, trades, candles),
                "mean_reversion": self.mean_reversion_strategy.analyze(market, orderbook, trades, candles),
                "cvd_divergence": self.cvd_strategy.analyze(market, orderbook, trades, candles),
            }
        except Exception as e:
            logger.error(f"Error getting sub-strategy details: {e}")
            return {}
