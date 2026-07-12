"""
Text-based dashboard for monitoring the trading bot.
"""

from datetime import datetime
from typing import Optional, Dict, List, Any
from .logger import get_logger

logger = get_logger(__name__)


def render_dashboard(trader: Any, position_tracker: Any):
    """
    Render a text-based dashboard to console.

    Args:
        trader: Trader instance with bankroll and trade history
        position_tracker: Position tracker with open positions
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build dashboard output
    output = []
    output.append("\n" + "=" * 100)
    output.append(f"KALSHI BITCOIN TRADING BOT - {timestamp}")
    output.append("=" * 100)

    # Account section
    output.append("\n" + "-" * 100)
    output.append("ACCOUNT")
    output.append("-" * 100)

    bankroll = getattr(trader, 'bankroll', 0)
    initial_bankroll = getattr(trader, 'initial_bankroll', 0)
    daily_pnl = getattr(trader, 'daily_pnl', 0)
    total_pnl = bankroll - initial_bankroll if initial_bankroll else 0

    pnl_color = "+" if daily_pnl >= 0 else ""
    total_pnl_color = "+" if total_pnl >= 0 else ""

    output.append(f"Bankroll: ${bankroll:,.2f} | Daily P&L: {pnl_color}${daily_pnl:,.2f} | Total P&L: {total_pnl_color}${total_pnl:,.2f}")

    # Positions section
    output.append("\n" + "-" * 100)
    output.append("OPEN POSITIONS")
    output.append("-" * 100)

    positions = getattr(position_tracker, 'positions', {})
    if positions:
        header = f"{'Ticker':<20} {'Side':<6} {'Size':<10} {'Entry Price':<15} {'Current Price':<15} {'Unrealized P&L':<15}"
        output.append(header)
        output.append("-" * 100)

        for ticker, position in positions.items():
            side = position.get('side', 'N/A')
            size = position.get('size', 0)
            entry_price = position.get('entry_price', 0)
            current_price = position.get('current_price', entry_price)
            unrealized_pnl = position.get('unrealized_pnl', 0)

            pnl_str = f"${unrealized_pnl:+,.2f}"
            output.append(
                f"{ticker:<20} {side:<6} {size:<10.2f} ${entry_price:<14.4f} ${current_price:<14.4f} {pnl_str:<15}"
            )
    else:
        output.append("No open positions")

    # Recent trades section
    output.append("\n" + "-" * 100)
    output.append("RECENT TRADES (Last 10)")
    output.append("-" * 100)

    trades = getattr(trader, 'recent_trades', [])
    if trades:
        header = f"{'Time':<20} {'Action':<8} {'Ticker':<20} {'Side':<6} {'Price':<12} {'Size':<10} {'Status':<12}"
        output.append(header)
        output.append("-" * 100)

        for trade in trades[-10:]:
            time_str = trade.get('timestamp', 'N/A')
            if isinstance(time_str, datetime):
                time_str = time_str.strftime("%H:%M:%S")

            action = trade.get('action', 'N/A')
            ticker = trade.get('ticker', 'N/A')
            side = trade.get('side', 'N/A')
            price = trade.get('price', 0)
            size = trade.get('size', 0)
            status = trade.get('status', 'OPEN')

            output.append(
                f"{time_str:<20} {action:<8} {ticker:<20} {side:<6} ${price:<11.4f} {size:<10.2f} {status:<12}"
            )
    else:
        output.append("No trades yet")

    # Active orders section
    output.append("\n" + "-" * 100)
    output.append("ACTIVE ORDERS")
    output.append("-" * 100)

    active_orders = getattr(trader, 'active_orders', [])
    if active_orders:
        header = f"{'Order ID':<25} {'Ticker':<20} {'Side':<6} {'Price':<12} {'Size':<10} {'Status':<12}"
        output.append(header)
        output.append("-" * 100)

        for order in active_orders:
            order_id = order.get('order_id', 'N/A')[:24]
            ticker = order.get('ticker', 'N/A')
            side = order.get('side', 'N/A')
            price = order.get('price', 0)
            size = order.get('size', 0)
            status = order.get('status', 'PENDING')

            output.append(
                f"{order_id:<25} {ticker:<20} {side:<6} ${price:<11.4f} {size:<10.2f} {status:<12}"
            )
    else:
        output.append("No active orders")

    # Strategy performance section
    output.append("\n" + "-" * 100)
    output.append("STRATEGY PERFORMANCE")
    output.append("-" * 100)

    stats = getattr(trader, 'stats', {})
    if stats:
        win_rate = stats.get('win_rate', 0)
        profit_factor = stats.get('profit_factor', 0)
        sharpe = stats.get('sharpe_ratio', 0)
        total_trades = stats.get('total_trades', 0)
        avg_trade_pnl = stats.get('avg_trade_pnl', 0)

        output.append(f"Win Rate: {win_rate:.1f}% | Profit Factor: {profit_factor:.2f}x | Sharpe: {sharpe:.2f}")
        output.append(f"Total Trades: {total_trades} | Avg Trade P&L: ${avg_trade_pnl:+,.2f}")
    else:
        output.append("No performance data yet")

    # Footer
    output.append("\n" + "=" * 100)

    # Print to console
    dashboard_text = "\n".join(output)
    print(dashboard_text)

    return dashboard_text
