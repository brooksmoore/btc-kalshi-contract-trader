"""
Order Management System for Kalshi Bitcoin Trading Bot

Handles:
- Limit order placement (GTC, avoiding taker fees)
- Order cancellation and lifecycle
- Duplicate order prevention
- Retry logic with exponential backoff
- Comprehensive order logging
"""

import logging
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """Order status enumeration"""
    PENDING = "pending"
    PLACED = "placed"
    RESTING = "resting"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Order representation"""
    order_id: str
    ticker: str
    side: str  # 'BUY' or 'SELL'
    price: float
    count: int
    status: OrderStatus
    placed_at: datetime
    filled_count: int = 0
    filled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    error: Optional[str] = None


class OrderManager:
    """
    Manages order lifecycle: creation, placement, cancellation, and tracking.
    Prevents duplicate orders and implements retry logic.
    """

    def __init__(self, kalshi_client, settings: dict):
        """
        Initialize order manager.

        Args:
            kalshi_client: Kalshi API client instance
            settings: Configuration dict with:
                - MAX_RETRIES: max retry attempts (default 3)
                - RETRY_BACKOFF: backoff multiplier (default 2.0)
        """
        self.kalshi_client = kalshi_client
        self.settings = settings
        # Support both dict and Settings dataclass
        if hasattr(settings, 'get'):
            self.max_retries = settings.get("MAX_RETRIES", 3)
            self.retry_backoff = settings.get("RETRY_BACKOFF", 2.0)
        else:
            self.max_retries = getattr(settings, 'MAX_RETRIES', 3)
            self.retry_backoff = getattr(settings, 'RETRY_BACKOFF', 2.0)

        # Track orders in memory
        self.orders: dict[str, Order] = {}  # order_id -> Order
        self.ticker_side_map: dict[Tuple[str, str], str] = {}  # (ticker, side) -> order_id

        logger.info(
            f"OrderManager initialized: max_retries={self.max_retries}, "
            f"retry_backoff={self.retry_backoff}"
        )

    async def place_limit_order(
        self, ticker: str, side: str, price: float, count: int
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Place a GTC (Good-Till-Cancel) limit order.
        Always uses limit orders to avoid taker fees.

        Args:
            ticker: Market ticker (e.g., 'BTCUSD')
            side: 'BUY' or 'SELL'
            price: Limit price
            count: Number of contracts

        Returns:
            (order_id: str, error: Optional[str])
        """
        # Check for duplicate
        if (ticker, side) in self.ticker_side_map:
            existing_order_id = self.ticker_side_map[(ticker, side)]
            error_msg = f"Order already exists for {ticker} {side}: {existing_order_id}"
            logger.warning(error_msg)
            return None, error_msg

        order = Order(
            order_id="PENDING",
            ticker=ticker,
            side=side,
            price=price,
            count=count,
            status=OrderStatus.PENDING,
            placed_at=datetime.utcnow(),
        )

        # Retry logic with exponential backoff
        for attempt in range(self.max_retries):
            try:
                logger.info(
                    f"Placing limit order (attempt {attempt + 1}/{self.max_retries}): "
                    f"{ticker} {side} {count} @ {price}"
                )

                # Call Kalshi API — side is "yes" or "no", price maps to yes_price/no_price
                create_kwargs = {
                    "ticker": ticker,
                    "side": side,
                    "type": "limit",
                    "count": count,
                }
                if side == "yes":
                    create_kwargs["yes_price"] = price
                else:
                    create_kwargs["no_price"] = price

                response = await self.kalshi_client.create_order(**create_kwargs)

                # Kalshi API wraps response in {"order": {...}}; paper trade returns flat dict
                order_data = response.get("order", response)
                order_id = order_data.get("order_id")
                order.order_id = order_id
                order.status = OrderStatus.PLACED

                # Store in tracking dicts
                self.orders[order_id] = order
                self.ticker_side_map[(ticker, side)] = order_id

                logger.info(
                    f"Order placed successfully: {order_id} for {ticker} {side} "
                    f"{count} @ {price}"
                )
                return order_id, None

            except Exception as e:
                error_msg = f"Order placement failed: {str(e)}"
                logger.error(f"{error_msg} (attempt {attempt + 1}/{self.max_retries})")

                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    backoff_time = (self.retry_backoff ** attempt)
                    logger.info(f"Retrying in {backoff_time:.1f}s...")
                    await asyncio.sleep(backoff_time)
                else:
                    order.status = OrderStatus.REJECTED
                    order.error = error_msg
                    logger.error(f"Order placement failed after {self.max_retries} attempts")
                    return None, error_msg

        return None, "Max retries exceeded"

    async def cancel_order(self, order_id: str) -> Tuple[bool, Optional[str]]:
        """
        Cancel a single order by ID.

        Args:
            order_id: Order ID to cancel

        Returns:
            (success: bool, error: Optional[str])
        """
        if order_id not in self.orders:
            error_msg = f"Order not found: {order_id}"
            logger.warning(error_msg)
            return False, error_msg

        order = self.orders[order_id]

        try:
            logger.info(f"Cancelling order: {order_id} ({order.ticker} {order.side})")

            await self.kalshi_client.cancel_order(order_id)

            order.status = OrderStatus.CANCELLED
            order.cancelled_at = datetime.utcnow()

            # Remove from ticker_side_map
            self.ticker_side_map.pop((order.ticker, order.side), None)

            logger.info(f"Order cancelled: {order_id}")
            return True, None

        except Exception as e:
            error_msg = f"Failed to cancel order {order_id}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def cancel_all_orders(self, ticker: Optional[str] = None) -> Tuple[int, Optional[str]]:
        """
        Cancel all open orders, optionally filtered by ticker.

        Args:
            ticker: Optional ticker to filter cancellations

        Returns:
            (cancelled_count: int, error: Optional[str])
        """
        cancelled_count = 0
        errors = []

        for order_id, order in list(self.orders.items()):
            if ticker and order.ticker != ticker:
                continue

            if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
                continue

            success, error = await self.cancel_order(order_id)
            if success:
                cancelled_count += 1
            else:
                errors.append(error)

        error_msg = "; ".join(errors) if errors else None
        logger.info(f"Cancelled {cancelled_count} orders" + (f" for {ticker}" if ticker else ""))

        return cancelled_count, error_msg

    async def get_open_orders(self) -> List[Order]:
        """
        Get all open orders.

        Returns:
            List of Order objects with status in [PLACED, RESTING, PARTIALLY_FILLED]
        """
        open_statuses = [
            OrderStatus.PLACED,
            OrderStatus.RESTING,
            OrderStatus.PARTIALLY_FILLED,
        ]
        return [o for o in self.orders.values() if o.status in open_statuses]

    async def sync_orders_from_api(self) -> None:
        """
        Sync local order state with Kalshi API.
        Fetches all orders from API and updates local tracking.
        """
        try:
            logger.info("Syncing orders from Kalshi API...")

            api_orders = await self.kalshi_client.get_orders()

            for api_order in api_orders:
                order_id = api_order.get("order_id")
                ticker = api_order.get("ticker")
                side = api_order.get("side")
                status = api_order.get("status")

                if order_id in self.orders:
                    # Update existing order
                    order = self.orders[order_id]
                    order.status = OrderStatus(status.lower())
                    order.filled_count = api_order.get("filled_count", 0)

                    logger.debug(
                        f"Updated order: {order_id} status={status}, filled={order.filled_count}"
                    )
                else:
                    # New order from API (shouldn't happen, but handle it)
                    order = Order(
                        order_id=order_id,
                        ticker=ticker,
                        side=side,
                        price=api_order.get("price", 0),
                        count=api_order.get("count", 0),
                        status=OrderStatus(status.lower()),
                        placed_at=datetime.utcnow(),
                        filled_count=api_order.get("filled_count", 0),
                    )
                    self.orders[order_id] = order
                    self.ticker_side_map[(ticker, side)] = order_id
                    logger.debug(f"Discovered new order from API: {order_id}")

            logger.info(f"Order sync complete: {len(self.orders)} orders tracked")

        except Exception as e:
            logger.error(f"Failed to sync orders from API: {str(e)}")

    async def update_order_status(self, order_id: str, fill: dict) -> None:
        """
        Update order status after a fill.

        Args:
            order_id: Order ID
            fill: Fill dict with filled_count, price, etc.
        """
        if order_id not in self.orders:
            logger.warning(f"Order not found for fill: {order_id}")
            return

        order = self.orders[order_id]
        filled_count = fill.get("filled_count", 0)
        order.filled_count = filled_count

        if filled_count >= order.count:
            order.status = OrderStatus.FILLED
            order.filled_at = datetime.utcnow()
            # Remove from ticker_side_map
            self.ticker_side_map.pop((order.ticker, order.side), None)
            logger.info(f"Order fully filled: {order_id}")
        elif filled_count > 0:
            order.status = OrderStatus.PARTIALLY_FILLED
            logger.info(f"Order partially filled: {order_id} ({filled_count}/{order.count})")

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)

    def get_orders_by_ticker(self, ticker: str) -> List[Order]:
        """Get all orders for a ticker."""
        return [o for o in self.orders.values() if o.ticker == ticker]

    def get_metrics(self) -> dict:
        """Get order metrics for logging/monitoring."""
        open_orders = [o for o in self.orders.values() if o.status not in [
            OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED
        ]]
        return {
            "total_orders_tracked": len(self.orders),
            "open_orders": len(open_orders),
            "filled_orders": len([o for o in self.orders.values() if o.status == OrderStatus.FILLED]),
            "cancelled_orders": len([o for o in self.orders.values() if o.status == OrderStatus.CANCELLED]),
        }
