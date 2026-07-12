"""
Structured logging configuration for the Kalshi trading bot.
"""

import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
import sys


class ColoredFormatter(logging.Formatter):
    """Formatter with colored output for console logs."""

    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        levelname = record.levelname
        color = self.COLORS.get(levelname, self.RESET)
        record.levelname = f"{color}{levelname}{self.RESET}"
        return super().format(record)


class CSVTradeFormatter(logging.Formatter):
    """Formatter for trade logs in CSV-like format."""

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).isoformat()
        action = getattr(record, 'action', 'TRADE')
        ticker = getattr(record, 'ticker', 'N/A')
        side = getattr(record, 'side', 'N/A')
        price = getattr(record, 'price', 'N/A')
        size = getattr(record, 'size', 'N/A')
        pnl = getattr(record, 'pnl', 'N/A')

        return f"{timestamp},{action},{ticker},{side},{price},{size},{pnl}"


def setup_logging(log_level=logging.INFO):
    """
    Setup structured logging for the bot.

    Args:
        log_level: Logging level for console handler (default: INFO)
    """
    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler (INFO or higher, colored)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (DEBUG, rotating)
    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "bot.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Trade logger (writes to trades.log in CSV format)
    trades_logger = logging.getLogger('trades')
    trades_logger.setLevel(logging.DEBUG)

    # Remove existing trade handlers
    for handler in trades_logger.handlers[:]:
        trades_logger.removeHandler(handler)

    trades_file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "trades.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5
    )
    trades_file_handler.setLevel(logging.DEBUG)
    trades_file_handler.setFormatter(CSVTradeFormatter())
    trades_logger.addHandler(trades_file_handler)

    # Prevent propagation to root logger for trades logger
    trades_logger.propagate = False


def get_logger(name):
    """
    Get a logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        logging.Logger instance
    """
    return logging.getLogger(name)


def log_trade(action, ticker, side, price, size, pnl=None):
    """
    Log a trade to the trades.log file.

    Args:
        action: Trade action (BUY, SELL, FILLED, CANCELLED)
        ticker: Contract ticker
        side: BUY or SELL
        price: Trade price
        size: Trade size
        pnl: Profit/loss (optional)
    """
    trades_logger = logging.getLogger('trades')
    trade_record = logging.LogRecord(
        name='trades',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg='',
        args=(),
        exc_info=None
    )
    trade_record.action = action
    trade_record.ticker = ticker
    trade_record.side = side
    trade_record.price = price
    trade_record.size = size
    trade_record.pnl = pnl if pnl is not None else 'N/A'

    trades_logger.handle(trade_record)
