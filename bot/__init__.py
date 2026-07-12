"""
Kalshi Bitcoin Contract Trading Bot
A production-grade automated trading system for short-term Bitcoin contracts on Kalshi.

Components:
- risk_manager: Position sizing, exposure limits, P&L tracking
- order_manager: Order placement, cancellation, lifecycle management
- position_tracker: Trade history, unrealized/realized P&L, position reconciliation
- trader: Main execution coordinator
"""

__version__ = "1.0.0"
__author__ = "Trading Bot Team"

from .risk_manager import RiskManager
from .order_manager import OrderManager
from .position_tracker import PositionTracker
from .trader import Trader

__all__ = [
    "RiskManager",
    "OrderManager",
    "PositionTracker",
    "Trader",
]
