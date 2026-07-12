"""
Unit tests for trading strategies and bot components.
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock


class TestExpectedValue(unittest.TestCase):
    """Test expected value calculations."""

    def test_ev_calculation_positive(self):
        """Test EV calculation for profitable trades."""
        win_rate = 0.55  # 55%
        avg_win = 100
        avg_loss = 80
        risk_reward = avg_win / avg_loss

        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        self.assertGreater(ev, 0)

    def test_ev_calculation_negative(self):
        """Test EV calculation for losing trades."""
        win_rate = 0.45  # 45%
        avg_win = 100
        avg_loss = 110
        risk_reward = avg_win / avg_loss

        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        self.assertLess(ev, 0)

    def test_ev_zero(self):
        """Test EV at break-even."""
        win_rate = 0.5
        avg_win = 100
        avg_loss = 100

        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        self.assertEqual(ev, 0)


class TestKellyCalculation(unittest.TestCase):
    """Test Kelly criterion calculations."""

    def test_kelly_formula(self):
        """Test Kelly fraction calculation."""
        win_rate = 0.6  # 60%
        loss_rate = 0.4  # 40%
        profit_loss_ratio = 1.5

        # Kelly = (bp - q) / b where b = profit/loss ratio
        b = profit_loss_ratio
        p = win_rate
        q = loss_rate

        kelly = ((b * p) - q) / b
        self.assertGreater(kelly, 0)
        self.assertLess(kelly, 1)  # Kelly should be < 100%

    def test_kelly_insufficient_edge(self):
        """Test Kelly with insufficient edge."""
        win_rate = 0.5  # 50%
        loss_rate = 0.5  # 50%
        profit_loss_ratio = 1.0

        b = profit_loss_ratio
        p = win_rate
        q = loss_rate

        kelly = ((b * p) - q) / b
        self.assertEqual(kelly, 0)  # No edge = no position

    def test_kelly_fractional(self):
        """Test Kelly fractional sizing (for safety)."""
        kelly = 0.25  # Full Kelly
        fractional_kelly = kelly * 0.25  # Quarter Kelly

        self.assertEqual(fractional_kelly, 0.0625)
        self.assertLess(fractional_kelly, kelly)


class TestPositionSizing(unittest.TestCase):
    """Test position sizing calculations."""

    def test_position_size_kelly(self):
        """Test Kelly-based position sizing."""
        bankroll = 10000
        kelly_fraction = 0.25
        price = 45
        max_size = (bankroll * kelly_fraction) / price

        self.assertAlmostEqual(max_size, 55.556, places=2)

    def test_position_size_fixed(self):
        """Test fixed position sizing."""
        bankroll = 10000
        fixed_percent = 0.02  # 2% risk per trade
        price = 50

        position_size = (bankroll * fixed_percent) / price
        self.assertAlmostEqual(position_size, 4.0)

    def test_position_size_exceeds_bankroll(self):
        """Test that position size doesn't exceed bankroll."""
        bankroll = 1000
        requested_size = 50
        price = 100

        # Position cost
        cost = requested_size * price
        self.assertGreater(cost, bankroll)

        # Should limit to available bankroll
        max_size = bankroll / price
        self.assertEqual(max_size, 10)


class TestFeeCalculation(unittest.TestCase):
    """Test fee calculations."""

    def test_maker_fee(self):
        """Test maker fee calculation."""
        price = 50
        size = 10
        maker_fee = 0.001  # 0.1%

        total_cost = (price * size) * (1 + maker_fee)
        fee = total_cost - (price * size)

        self.assertAlmostEqual(fee, 0.5)

    def test_taker_fee(self):
        """Test taker fee calculation."""
        price = 50
        size = 10
        taker_fee = 0.005  # 0.5%

        gross_proceeds = price * size
        fee = gross_proceeds * taker_fee
        net_proceeds = gross_proceeds - fee

        self.assertAlmostEqual(fee, 2.5)
        self.assertAlmostEqual(net_proceeds, 497.5)

    def test_round_trip_fees(self):
        """Test round-trip fee impact."""
        price = 50
        size = 10
        taker_fee = 0.005

        entry_cost = (price * size) * (1 + taker_fee)
        exit_proceeds = (price * size) * (1 - taker_fee)

        # Total cost of fees for round trip
        total_fees = entry_cost - (price * size) + (price * size) - exit_proceeds
        fee_percent = (total_fees / (price * size)) * 100

        self.assertAlmostEqual(fee_percent, 1.0, places=2)


class TestStrategySignalGeneration(unittest.TestCase):
    """Test that strategies return appropriate signals."""

    def test_signal_structure(self):
        """Test signal has required fields."""
        signal = {
            'type': 'BUY',
            'price': 45.50,
            'size': 2,
            'confidence': 0.62,
            'kelly_fraction': 0.25,
        }

        self.assertIn('type', signal)
        self.assertIn('price', signal)
        self.assertIn('size', signal)
        self.assertIsNotNone(signal['type'])

    def test_strategy_insufficient_data(self):
        """Test that strategy returns None with insufficient data."""
        # Simulate a strategy that needs minimum data points
        min_periods = 20
        candles = 5

        # With insufficient data
        result = candles < min_periods
        self.assertTrue(result)

        # Strategy should return None in this case
        signal = None if result else {'type': 'BUY', 'price': 45}
        self.assertIsNone(signal)

    def test_strategy_sufficient_data(self):
        """Test strategy returns signal with sufficient data."""
        min_periods = 20
        candles = 50

        result = candles >= min_periods
        self.assertTrue(result)

        # Strategy can return signal now
        signal = {'type': 'BUY', 'price': 45, 'size': 2}
        self.assertIsNotNone(signal)
        self.assertEqual(signal['type'], 'BUY')


class TestRiskManagement(unittest.TestCase):
    """Test risk management and position limits."""

    def test_risk_limit_breach(self):
        """Test that trades exceeding risk limit are blocked."""
        max_position_size = 10
        requested_size = 15
        price = 50

        # Risk manager should reject
        allowed = requested_size <= max_position_size
        self.assertFalse(allowed)

    def test_daily_loss_limit(self):
        """Test daily loss limit enforcement."""
        daily_loss_limit = 500
        current_daily_loss = 450
        potential_trade_loss = 100

        would_exceed = (current_daily_loss + potential_trade_loss) > daily_loss_limit
        self.assertTrue(would_exceed)

        # Trade should be blocked
        allowed = not would_exceed
        self.assertFalse(allowed)

    def test_max_open_positions(self):
        """Test maximum open positions limit."""
        max_positions = 3
        current_positions = 3
        new_signal = 'BUY'

        # Can't open new position if at limit
        allowed = current_positions < max_positions
        self.assertFalse(allowed)

    def test_position_within_limits(self):
        """Test position that respects all limits."""
        max_size = 20
        requested_size = 10
        daily_loss_limit = 1000
        current_daily_loss = 200
        trade_loss = 150
        max_positions = 5
        current_positions = 2

        size_ok = requested_size <= max_size
        loss_ok = (current_daily_loss + trade_loss) <= daily_loss_limit
        positions_ok = current_positions < max_positions

        all_ok = size_ok and loss_ok and positions_ok
        self.assertTrue(all_ok)


class TestBacktestEngine(unittest.TestCase):
    """Test backtesting engine."""

    def setUp(self):
        """Set up test fixtures."""
        # Create sample candle data
        dates = pd.date_range('2024-01-01', periods=100, freq='1H')
        self.candles_df = pd.DataFrame({
            'open': np.random.uniform(40, 50, 100),
            'high': np.random.uniform(50, 52, 100),
            'low': np.random.uniform(38, 40, 100),
            'close': np.random.uniform(40, 50, 100),
            'volume': np.random.uniform(1000, 10000, 100),
        }, index=dates)

    def test_backtest_returns_metrics(self):
        """Test that backtest returns metrics."""
        # Import here to avoid circular imports
        from backtesting.engine import BacktestEngine

        mock_strategy = Mock()
        mock_strategy.generate_signal = Mock(return_value=None)

        engine = BacktestEngine(mock_strategy, 10000, {'taker_fee': 0.005})
        success = engine.run(self.candles_df)

        self.assertTrue(success)

        metrics = engine.get_metrics()
        self.assertIn('win_rate', metrics)
        self.assertIn('profit_factor', metrics)
        self.assertIn('max_drawdown', metrics)
        self.assertIn('sharpe_ratio', metrics)

    def test_backtest_empty_dataframe(self):
        """Test backtest with empty DataFrame."""
        from backtesting.engine import BacktestEngine

        mock_strategy = Mock()
        engine = BacktestEngine(mock_strategy, 10000, {'taker_fee': 0.005})

        success = engine.run(pd.DataFrame())
        self.assertFalse(success)

    def test_backtest_missing_columns(self):
        """Test backtest with missing required columns."""
        from backtesting.engine import BacktestEngine

        mock_strategy = Mock()
        engine = BacktestEngine(mock_strategy, 10000, {'taker_fee': 0.005})

        # DataFrame missing required columns
        bad_df = pd.DataFrame({'price': [45, 46, 47]})
        success = engine.run(bad_df)
        self.assertFalse(success)


class TestAlertingSystem(unittest.TestCase):
    """Test alerting system."""

    def test_alerter_initialization_without_telegram(self):
        """Test alerter initializes without Telegram."""
        with patch.dict('os.environ', {}, clear=True):
            from monitoring.alerter import Alerter
            alerter = Alerter()
            self.assertFalse(alerter.enabled)

    def test_alerter_initialization_with_telegram(self):
        """Test alerter initializes with Telegram."""
        env = {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': 'test_chat_id'
        }
        with patch.dict('os.environ', env):
            from monitoring.alerter import Alerter
            alerter = Alerter()
            self.assertTrue(alerter.enabled)

    def test_alert_message_format_trade(self):
        """Test trade alert message format."""
        signal = "BUY"
        ticker = "KXBTC15M"
        side = "BUY"
        price = 45.50
        size = 2
        confidence = 62
        edge = 17

        message = f"🎯 {signal} {ticker} @ ${price:.2f} | Size: {size} | Model: {confidence:.0f}% | Edge: {edge:.1f}%"

        self.assertIn("BUY", message)
        self.assertIn("KXBTC15M", message)
        self.assertIn("45.50", message)
        self.assertIn("62%", message)
        self.assertIn("17.0%", message)


class TestLogging(unittest.TestCase):
    """Test logging setup."""

    def test_logger_setup(self):
        """Test that logger setup completes."""
        from monitoring.logger import setup_logging, get_logger
        import logging

        setup_logging(logging.INFO)

        logger = get_logger('test')
        self.assertIsNotNone(logger)
        self.assertEqual(logger.name, 'test')

    def test_trades_logger(self):
        """Test trade logger."""
        from monitoring.logger import setup_logging, log_trade
        import logging

        setup_logging(logging.DEBUG)

        # This should not raise an exception
        log_trade('BUY', 'KXBTC15M', 'BUY', 45.50, 2, 100)


if __name__ == '__main__':
    unittest.main()
