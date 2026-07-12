"""
Position and Trade Tracking System for Kalshi Bitcoin Trading Bot

Uses aiosqlite for persistent storage with tables:
- positions: Current open positions
- trades: Historical trades with MAE/MFE tracking
- daily_pnl: Daily P&L snapshots

Handles:
- Position reconciliation with API
- P&L calculations (realized and unrealized)
- Trade history and analysis
- Max Adverse Excursion (MAE) and Max Favorable Excursion (MFE) tracking
"""

import logging
import sqlite3
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import aiosqlite
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position"""
    ticker: str
    side: str  # 'BUY' or 'SELL'
    quantity: int
    entry_price: float
    entry_time: datetime
    current_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    mae: float = 0.0  # Max Adverse Excursion
    mfe: float = 0.0  # Max Favorable Excursion
    order_id: Optional[str] = None

    def calculate_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L given current price."""
        if self.side == "BUY":
            return (current_price - self.entry_price) * self.quantity
        else:  # SELL
            return (self.entry_price - current_price) * self.quantity

    def update_excursion(self, price: float) -> None:
        """Update MAE and MFE based on new price."""
        pnl = self.calculate_pnl(price)

        if pnl < self.mae:
            self.mae = pnl

        if pnl > self.mfe:
            self.mfe = pnl


@dataclass
class Trade:
    """Represents a completed trade"""
    trade_id: str
    ticker: str
    side: str
    quantity: int
    entry_price: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    realized_pnl: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    duration: Optional[timedelta] = None
    notes: str = ""


class PositionTracker:
    """
    Tracks positions, trades, and P&L using persistent aiosqlite database.
    """

    def __init__(self, db_path: str = "trades.db"):
        """
        Initialize position tracker.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

        # In-memory cache
        self.positions: Dict[str, Position] = {}  # ticker -> Position
        self.trades: List[Trade] = []

        logger.info(f"PositionTracker initialized with db_path={db_path}")

    async def initialize(self) -> None:
        """Initialize database and create tables."""
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging for concurrency

        # Create tables
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                current_price REAL,
                unrealized_pnl REAL DEFAULT 0,
                mae REAL DEFAULT 0,
                mfe REAL DEFAULT 0,
                order_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, side)
            )
        """)

        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                exit_price REAL,
                exit_time TEXT,
                realized_pnl REAL DEFAULT 0,
                mae REAL DEFAULT 0,
                mfe REAL DEFAULT 0,
                duration_seconds INTEGER,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                realized_pnl REAL DEFAULT 0,
                unrealized_pnl REAL DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self.db.commit()
        logger.info(f"Database initialized: {self.db_path}")

    async def close(self) -> None:
        """Close database connection."""
        if self.db:
            await self.db.close()
            logger.info("Database connection closed")

    async def sync_positions(self, kalshi_client) -> None:
        """
        Fetch current positions from Kalshi API and reconcile with local DB.

        Args:
            kalshi_client: Kalshi API client instance
        """
        try:
            logger.info("Syncing positions from Kalshi API...")

            api_positions = await kalshi_client.get_positions()

            for api_pos in api_positions:
                ticker = api_pos.get("ticker")
                side = api_pos.get("side")
                quantity = api_pos.get("quantity", 0)
                entry_price = api_pos.get("entry_price", 0)

                if quantity == 0:
                    # Position closed
                    await self._close_position(ticker, side)
                else:
                    # Update or create position
                    position = Position(
                        ticker=ticker,
                        side=side,
                        quantity=quantity,
                        entry_price=entry_price,
                        entry_time=datetime.utcnow(),
                    )
                    self.positions[ticker] = position

                    await self._upsert_position(position)

            logger.info(f"Position sync complete: {len(self.positions)} open positions")

        except Exception as e:
            logger.error(f"Failed to sync positions from API: {str(e)}")

    async def get_open_positions(self) -> List[Position]:
        """Get list of all open positions."""
        return list(self.positions.values())

    def get_position(self, ticker: str) -> Optional[Position]:
        """Get position by ticker, or None if not open."""
        return self.positions.get(ticker)

    async def record_fill(self, fill: dict) -> None:
        """
        Record a trade fill and update position.

        Args:
            fill: dict with keys:
                - order_id: Order ID
                - ticker: Market ticker
                - side: 'BUY' or 'SELL'
                - quantity: Number of contracts
                - price: Fill price
                - timestamp: Fill timestamp
        """
        ticker = fill.get("ticker")
        side = fill.get("side")
        quantity = fill.get("quantity", 0)
        price = fill.get("price", 0)
        timestamp = fill.get("timestamp", datetime.utcnow())
        order_id = fill.get("order_id")

        try:
            # Update or create position
            if ticker in self.positions:
                position = self.positions[ticker]
                # Average the entry price (simplified; can be more sophisticated)
                total_quantity = position.quantity + quantity
                position.entry_price = (
                    (position.entry_price * position.quantity + price * quantity) / total_quantity
                )
                position.quantity = total_quantity
            else:
                position = Position(
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    entry_price=price,
                    entry_time=timestamp,
                    order_id=order_id,
                )
                self.positions[ticker] = position

            await self._upsert_position(position)
            logger.info(
                f"Fill recorded: {ticker} {side} {quantity} @ {price} "
                f"(position quantity now: {position.quantity})"
            )

        except Exception as e:
            logger.error(f"Failed to record fill: {str(e)}")

    async def close_position(
        self, ticker: str, exit_price: float, exit_time: Optional[datetime] = None
    ) -> None:
        """
        Close a position and record it as a completed trade.

        Args:
            ticker: Market ticker
            exit_price: Exit price
            exit_time: Exit timestamp
        """
        if ticker not in self.positions:
            logger.warning(f"No open position to close: {ticker}")
            return

        position = self.positions[ticker]
        exit_time = exit_time or datetime.utcnow()

        # Calculate realized P&L
        if position.side == "BUY":
            realized_pnl = (exit_price - position.entry_price) * position.quantity
        else:  # SELL
            realized_pnl = (position.entry_price - exit_price) * position.quantity

        # Create trade record
        trade = Trade(
            trade_id=f"{ticker}_{position.entry_time.timestamp()}",
            ticker=ticker,
            side=position.side,
            quantity=position.quantity,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            exit_price=exit_price,
            exit_time=exit_time,
            realized_pnl=realized_pnl,
            mae=position.mae,
            mfe=position.mfe,
            duration=exit_time - position.entry_time,
        )

        await self._insert_trade(trade)
        self.trades.append(trade)

        # Remove from positions
        del self.positions[ticker]
        await self._delete_position(ticker)

        logger.info(
            f"Position closed: {ticker} {position.side} {position.quantity} "
            f"@ exit {exit_price}, PnL: {realized_pnl:.2f}"
        )

    def calculate_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total unrealized P&L across all positions.

        Args:
            current_prices: dict of ticker -> current_price

        Returns:
            Total unrealized P&L
        """
        total_pnl = 0.0
        for ticker, position in self.positions.items():
            current_price = current_prices.get(ticker, position.entry_price)
            position.current_price = current_price
            pnl = position.calculate_pnl(current_price)
            position.unrealized_pnl = pnl
            position.update_excursion(current_price)
            total_pnl += pnl

        return total_pnl

    async def calculate_realized_pnl(self, date: Optional[datetime] = None) -> float:
        """
        Calculate realized P&L for a specific date.

        Args:
            date: Date to calculate for (default: today)

        Returns:
            Realized P&L for the date
        """
        if date is None:
            date = datetime.utcnow().date()
        else:
            date = date.date() if isinstance(date, datetime) else date

        date_str = date.isoformat()

        try:
            cursor = await self.db.execute(
                "SELECT realized_pnl FROM daily_pnl WHERE date = ?",
                (date_str,),
            )
            row = await cursor.fetchone()
            if row:
                return row[0]
        except Exception as e:
            logger.error(f"Failed to get realized PnL for {date}: {str(e)}")

        return 0.0

    async def get_trade_history(self, days: int = 30) -> pd.DataFrame:
        """
        Get DataFrame of recent trades for analysis.

        Args:
            days: Number of days to retrieve

        Returns:
            DataFrame with columns: ticker, side, quantity, entry_price, exit_price,
                                   realized_pnl, duration, mae, mfe
        """
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()

            cursor = await self.db.execute(
                """
                SELECT trade_id, ticker, side, quantity, entry_price, exit_price,
                       realized_pnl, duration_seconds, mae, mfe, entry_time, exit_time
                FROM trades
                WHERE exit_time >= ?
                ORDER BY exit_time DESC
                """,
                (cutoff_date,),
            )
            rows = await cursor.fetchall()

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(
                rows,
                columns=[
                    "trade_id", "ticker", "side", "quantity", "entry_price", "exit_price",
                    "realized_pnl", "duration_seconds", "mae", "mfe", "entry_time", "exit_time"
                ],
            )

            df["entry_time"] = pd.to_datetime(df["entry_time"])
            df["exit_time"] = pd.to_datetime(df["exit_time"])
            df["duration"] = pd.to_timedelta(df["duration_seconds"], unit="s")

            return df

        except Exception as e:
            logger.error(f"Failed to get trade history: {str(e)}")
            return pd.DataFrame()

    async def record_daily_pnl(self, realized_pnl: float, unrealized_pnl: float, date: Optional[datetime] = None) -> None:
        """Record daily P&L snapshot."""
        if date is None:
            date = datetime.utcnow().date()
        else:
            date = date.date() if isinstance(date, datetime) else date

        date_str = date.isoformat()
        total_pnl = realized_pnl + unrealized_pnl

        try:
            await self.db.execute(
                """
                INSERT OR REPLACE INTO daily_pnl (date, realized_pnl, unrealized_pnl, total_pnl)
                VALUES (?, ?, ?, ?)
                """,
                (date_str, realized_pnl, unrealized_pnl, total_pnl),
            )
            await self.db.commit()
            logger.debug(f"Daily PnL recorded for {date_str}: realized={realized_pnl:.2f}, unrealized={unrealized_pnl:.2f}")
        except Exception as e:
            logger.error(f"Failed to record daily PnL: {str(e)}")

    # --- Private Methods ---

    async def _upsert_position(self, position: Position) -> None:
        """Insert or update position in database."""
        try:
            await self.db.execute(
                """
                INSERT INTO positions (ticker, side, quantity, entry_price, entry_time,
                                      current_price, unrealized_pnl, mae, mfe, order_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(ticker, side) DO UPDATE SET
                    quantity = excluded.quantity,
                    entry_price = excluded.entry_price,
                    current_price = excluded.current_price,
                    unrealized_pnl = excluded.unrealized_pnl,
                    mae = excluded.mae,
                    mfe = excluded.mfe,
                    order_id = excluded.order_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    position.ticker, position.side, position.quantity, position.entry_price,
                    position.entry_time.isoformat(), position.current_price,
                    position.unrealized_pnl, position.mae, position.mfe, position.order_id,
                ),
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to upsert position: {str(e)}")

    async def _insert_trade(self, trade: Trade) -> None:
        """Insert completed trade into database."""
        try:
            duration_seconds = int(trade.duration.total_seconds()) if trade.duration else None
            await self.db.execute(
                """
                INSERT INTO trades (trade_id, ticker, side, quantity, entry_price, entry_time,
                                   exit_price, exit_time, realized_pnl, mae, mfe, duration_seconds, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.trade_id, trade.ticker, trade.side, trade.quantity,
                    trade.entry_price, trade.entry_time.isoformat(),
                    trade.exit_price, trade.exit_time.isoformat() if trade.exit_time else None,
                    trade.realized_pnl, trade.mae, trade.mfe, duration_seconds, trade.notes,
                ),
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to insert trade: {str(e)}")

    async def _delete_position(self, ticker: str) -> None:
        """Delete position from database."""
        try:
            await self.db.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to delete position: {str(e)}")

    async def _close_position(self, ticker: str, side: str) -> None:
        """Close position in database."""
        try:
            await self.db.execute(
                "DELETE FROM positions WHERE ticker = ? AND side = ?",
                (ticker, side),
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to close position: {str(e)}")

    def get_metrics(self) -> dict:
        """Get position tracker metrics."""
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return {
            "open_positions": len(self.positions),
            "total_unrealized_pnl": total_unrealized,
            "total_trades_recorded": len(self.trades),
            "positions": {
                ticker: {
                    "side": pos.side,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                }
                for ticker, pos in self.positions.items()
            },
        }
