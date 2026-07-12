"""
Alerting system for the Kalshi trading bot.
Supports Telegram notifications with fallback to console logging.
"""

import os
import asyncio
import httpx
from typing import Optional
from .logger import get_logger

logger = get_logger(__name__)


class Alerter:
    """Handles alert notifications via Telegram or console."""

    def __init__(self):
        """Initialize alerter with Telegram credentials if available."""
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = self.telegram_bot_token is not None and self.telegram_chat_id is not None

        if self.enabled:
            logger.info(
                f"Telegram alerting enabled for chat {self.telegram_chat_id[:10]}..."
            )
        else:
            logger.info("Telegram alerting disabled - using console logging fallback")

    async def send_trade_alert(self, signal: str, ticker: str, side: str, price: float, size: float, model_confidence: float, edge: float):
        """
        Send trade signal alert.

        Args:
            signal: Signal type (BUY/SELL)
            ticker: Contract ticker
            side: BUY or SELL
            price: Entry price
            size: Position size
            model_confidence: Model confidence percentage (0-100)
            edge: Expected edge percentage
        """
        message = f"🎯 {signal} {ticker} @ ${price:.2f} | Size: {size} | Model: {model_confidence:.0f}% | Edge: {edge:.1f}%"
        await self._send_message(message)

    async def send_fill_alert(self, ticker: str, side: str, size: float, price: float):
        """
        Send order fill alert.

        Args:
            ticker: Contract ticker
            side: BUY or SELL
            size: Filled size
            price: Fill price
        """
        message = f"✅ FILLED: {side} {size}x {ticker} @ ${price:.2f}"
        await self._send_message(message)

    async def send_pnl_alert(self, daily_pnl: float, win_rate: Optional[float] = None, trades_count: int = 0):
        """
        Send daily P&L summary alert.

        Args:
            daily_pnl: Daily profit/loss
            win_rate: Win rate percentage (optional)
            trades_count: Number of trades today (optional)
        """
        emoji = "📈" if daily_pnl > 0 else "📉"
        message = f"{emoji} Daily P&L: ${daily_pnl:+.2f}"

        if win_rate is not None:
            message += f" | Win Rate: {win_rate:.1f}%"

        if trades_count > 0:
            message += f" | Trades: {trades_count}"

        await self._send_message(message)

    async def send_error_alert(self, error: str):
        """
        Send error notification.

        Args:
            error: Error message
        """
        message = f"⚠️ ERROR: {error}"
        await self._send_message(message)

    async def send_status(self, message: str):
        """
        Send general status message.

        Args:
            message: Status message
        """
        await self._send_message(f"ℹ️ {message}")

    async def _send_message(self, message: str):
        """
        Internal method to send message via Telegram or console.

        Args:
            message: Message to send
        """
        if self.enabled:
            await self._send_telegram(message)
        else:
            logger.info(f"[ALERT] {message}")

    async def _send_telegram(self, message: str):
        """
        Send message via Telegram API.

        Args:
            message: Message to send
        """
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code != 200:
                    logger.warning(
                        f"Telegram API error: {response.status_code} - {response.text}"
                    )
        except asyncio.TimeoutError:
            logger.warning("Telegram API timeout")
        except Exception as e:
            logger.warning(f"Failed to send Telegram alert: {str(e)}")
