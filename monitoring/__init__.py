"""
Monitoring module for the Kalshi Bitcoin trading bot.
Provides logging, alerting, and dashboard functionality.
"""

from .logger import setup_logging, get_logger
from .alerter import Alerter
from .dashboard import render_dashboard

__all__ = ["setup_logging", "get_logger", "Alerter", "render_dashboard"]
