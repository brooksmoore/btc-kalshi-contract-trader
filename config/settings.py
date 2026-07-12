"""
Configuration settings for the Kalshi Bitcoin trading bot.
Loads all settings from .env file using python-dotenv.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


# Load environment variables from .env file
load_dotenv()


@dataclass
class Settings:
    """Settings dataclass with all configuration parameters."""

    # API Configuration
    KALSHI_API_KEY_ID: str = os.getenv("KALSHI_API_KEY_ID", "")
    KALSHI_PRIVATE_KEY_PATH: str = os.getenv("KALSHI_PRIVATE_KEY_PATH", "./kalshi_private_key.pem")
    KALSHI_ENV: str = os.getenv("KALSHI_ENV", "demo")

    # Trading Parameters
    STARTING_BANKROLL: float = float(os.getenv("STARTING_BANKROLL", "100.0"))
    MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "25.0"))
    MAX_POSITION_SIZE: float = float(os.getenv("MAX_POSITION_SIZE", "5.0"))
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
    KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.25"))
    MIN_EDGE_THRESHOLD: float = float(os.getenv("MIN_EDGE_THRESHOLD", "0.05"))
    MAX_CONCENTRATION: float = float(os.getenv("MAX_CONCENTRATION", "0.40"))

    # Aliases expected by RiskManager
    @property
    def BANKROLL(self) -> float:
        return self.STARTING_BANKROLL

    @property
    def CORRELATED_MARKETS(self):
        return []  # checked dynamically by ticker prefix instead

    # Operational Parameters
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "120"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Notifications
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")

    # API Endpoints
    PROD_BASE_URL: str = "https://api.elections.kalshi.com/trade-api/v2"
    DEMO_BASE_URL: str = "https://demo-api.kalshi.co/trade-api/v2"
    WS_PROD_URL: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    WS_DEMO_URL: str = "wss://demo-api.kalshi.co/trade-api/ws/v2"

    # Bitcoin Ticker Prefixes
    BTC_15M_TICKER: str = "KXBTC15M"
    BTC_DAILY_TICKER: str = "KXBTCD"
    BTC_GENERAL_TICKER: str = "KXBTC"

    @property
    def base_url(self) -> str:
        """Return the appropriate base URL based on KALSHI_ENV."""
        if self.KALSHI_ENV.lower() == "prod":
            return self.PROD_BASE_URL
        return self.DEMO_BASE_URL

    @property
    def ws_url(self) -> str:
        """Return the appropriate WebSocket URL based on KALSHI_ENV."""
        if self.KALSHI_ENV.lower() == "prod":
            return self.WS_PROD_URL
        return self.WS_DEMO_URL

    def calculate_taker_fee(self, price: float) -> float:
        """
        Calculate taker fee based on contract price.

        Formula: 0.07 * price * (1 - price)
        Capped at 1.75 cents (0.0175).

        Args:
            price: The contract price (typically 0-1)

        Returns:
            The taker fee as a decimal amount
        """
        raw_fee = 0.07 * price * (1 - price)
        return min(raw_fee, 0.0175)

    def get_private_key_path(self) -> Path:
        """Get the private key path as a Path object."""
        return Path(self.KALSHI_PRIVATE_KEY_PATH).expanduser().absolute()

    def __post_init__(self):
        """Validate settings after initialization."""
        if not self.KALSHI_API_KEY_ID:
            raise ValueError("KALSHI_API_KEY_ID must be set in environment variables")

        if self.KALSHI_ENV.lower() not in ("demo", "prod"):
            raise ValueError("KALSHI_ENV must be either 'demo' or 'prod'")

        if self.STARTING_BANKROLL <= 0:
            raise ValueError("STARTING_BANKROLL must be positive")

        if not 0 < self.KELLY_FRACTION <= 1:
            raise ValueError("KELLY_FRACTION must be between 0 and 1")

        if self.MAX_DAILY_LOSS >= self.STARTING_BANKROLL:
            raise ValueError("MAX_DAILY_LOSS must be less than STARTING_BANKROLL")

        if self.SCAN_INTERVAL_SECONDS < 1:
            raise ValueError("SCAN_INTERVAL_SECONDS must be at least 1")


# Lazy global settings instance — only instantiated when first accessed,
# so importing this module doesn't crash if env vars aren't set yet.
_settings_instance = None


def get_settings() -> Settings:
    """Return the global Settings singleton, creating it on first call."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance
