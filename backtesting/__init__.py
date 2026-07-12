"""
Backtesting module for the Kalshi Bitcoin trading bot.
Provides backtesting engine and runner for strategy validation.
"""

from .engine import BacktestEngine
from .runner import BacktestRunner

__all__ = ["BacktestEngine", "BacktestRunner"]
