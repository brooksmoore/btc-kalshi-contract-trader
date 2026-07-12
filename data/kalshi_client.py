"""
Kalshi API client with RSA-PSS signature authentication.
Handles all HTTP communication with the Kalshi trading platform.
"""

import base64
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from config import get_settings


logger = logging.getLogger(__name__)


class KalshiClient:
    """
    Client for interacting with Kalshi API.

    Handles RSA-PSS authentication, HTTP requests, and response parsing.
    """

    def __init__(
        self,
        api_key_id: str,
        private_key_path: str,
        base_url: Optional[str] = None,
        paper_trade: bool = False,
    ):
        """
        Initialize Kalshi client.

        Args:
            api_key_id: API key ID for authentication
            private_key_path: Path to RSA private key file (.pem)
            base_url: Base URL for API (defaults to settings.base_url)
            paper_trade: If True, log orders instead of executing them
        """
        self.api_key_id = api_key_id
        self.private_key_path = Path(private_key_path).expanduser().absolute()
        self.base_url = base_url or get_settings().base_url
        self.paper_trade = paper_trade

        # Load private key
        self._load_private_key()

        # HTTP client
        self.client = httpx.AsyncClient(base_url=self.base_url)

        logger.info(
            f"Initialized KalshiClient (env={get_settings().KALSHI_ENV}, "
            f"paper_trade={paper_trade})"
        )

    def _load_private_key(self) -> None:
        """Load RSA private key from file."""
        if not self.private_key_path.exists():
            raise FileNotFoundError(f"Private key not found: {self.private_key_path}")

        try:
            with open(self.private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )
            logger.debug(f"Loaded private key from {self.private_key_path}")
        except Exception as e:
            logger.error(f"Failed to load private key: {e}")
            raise

    def _sign_request(self, timestamp_ms: int, method: str, path: str) -> str:
        """
        Sign a request using RSA-PSS.

        Args:
            timestamp_ms: Current timestamp in milliseconds
            method: HTTP method (GET, POST, DELETE, etc.)
            path: Request path without query parameters

        Returns:
            Base64-encoded signature
        """
        # Message to sign: timestamp + method + path
        message = f"{timestamp_ms}{method}{path}".encode("utf-8")

        # Sign with RSA-PSS using SHA256
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return base64.b64encode(signature).decode("utf-8")

    def _get_headers(self, method: str, path: str) -> Dict[str, str]:
        """
        Generate authentication headers for a request.

        Args:
            method: HTTP method
            path: Request path (without query parameters)

        Returns:
            Dictionary of headers including authentication
        """
        timestamp_ms = int(time.time() * 1000)
        signature = self._sign_request(timestamp_ms, method, path)

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated HTTP request.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            path: API endpoint path
            json_data: JSON body for POST/PUT requests
            params: Query parameters

        Returns:
            Parsed JSON response

        Raises:
            httpx.HTTPError: If request fails
        """
        headers = self._get_headers(method, path)

        try:
            response = await self.client.request(
                method, path, headers=headers, json=json_data, params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error {e.response.status_code} on {method} {path}: "
                f"{e.response.text}"
            )
            raise
        except Exception as e:
            logger.error(f"Request failed for {method} {path}: {e}")
            raise

    async def get_markets(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Get list of markets.

        Args:
            series_ticker: Optional series ticker filter
            status: Market status filter (default: "open")
            limit: Maximum number of markets to return

        Returns:
            List of market dictionaries
        """
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker

        return await self._request("GET", "/markets", params=params)

    async def get_market(self, ticker: str) -> Dict[str, Any]:
        """
        Get a specific market by ticker.

        Args:
            ticker: Market ticker

        Returns:
            Market dictionary
        """
        return await self._request("GET", f"/markets/{ticker}")

    async def get_event(self, event_ticker: str) -> Dict[str, Any]:
        """
        Get event details.

        Args:
            event_ticker: Event ticker

        Returns:
            Event dictionary
        """
        return await self._request("GET", f"/events/{event_ticker}")

    async def get_orderbook(self, ticker: str) -> Dict[str, Any]:
        """
        Get orderbook for a market.

        Args:
            ticker: Market ticker

        Returns:
            Orderbook dictionary with bids and asks
        """
        return await self._request("GET", f"/markets/{ticker}/orderbook")

    async def get_trades(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent trades for a market.

        Args:
            ticker: Market ticker
            limit: Maximum trades to return

        Returns:
            List of trade dictionaries
        """
        params = {"limit": limit}
        return await self._request("GET", f"/markets/{ticker}/trades", params=params)

    async def get_market_history(
        self, ticker: str, limit: int = 1000, period_interval: str = "1m"
    ) -> List[Dict[str, Any]]:
        """
        Get candlestick history for a market.

        Args:
            ticker: Market ticker
            limit: Maximum candlesticks to return
            period_interval: Interval (e.g., "1m", "5m", "1h", "1d")

        Returns:
            List of candlestick dictionaries
        """
        params = {"limit": limit, "period_interval": period_interval}
        return await self._request(
            "GET", f"/markets/{ticker}/candlesticks", params=params
        )

    async def create_order(
        self,
        ticker: str,
        side: str,
        type: str = "limit",
        yes_price: Optional[float] = None,
        no_price: Optional[float] = None,
        count: int = 1,
        expiration_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create an order.

        Args:
            ticker: Market ticker
            side: "yes" or "no" (which contract type to buy)
            type: "limit" or "market"
            yes_price: Price for YES contracts (if ordering YES)
            no_price: Price for NO contracts (if ordering NO)
            count: Number of contracts
            expiration_ts: Unix timestamp in milliseconds for order expiration

        Returns:
            Order dictionary with order_id
        """
        if self.paper_trade:
            logger.info(
                f"[PAPER] Would create {side} {count} contracts @ "
                f"{yes_price or no_price} for {ticker}"
            )
            return {"order_id": f"paper_{int(time.time())}", "ticker": ticker}

        payload = {
            "ticker": ticker,
            "side": side,
            "type": type,
            "count": count,
        }

        if type == "limit":
            if side == "yes" and yes_price is not None:
                payload["yes_price"] = yes_price
            elif side == "no" and no_price is not None:
                payload["no_price"] = no_price
            else:
                raise ValueError(
                    f"Price required for limit order: yes_price={yes_price}, "
                    f"no_price={no_price}"
                )

        if expiration_ts is not None:
            payload["expiration_ts"] = expiration_ts

        return await self._request("POST", "/portfolio/orders", json_data=payload)

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            Response dictionary
        """
        if self.paper_trade:
            logger.info(f"[PAPER] Would cancel order {order_id}")
            return {"order_id": order_id, "status": "canceled"}

        return await self._request("DELETE", f"/portfolio/orders/{order_id}")

    async def get_orders(
        self, ticker: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get user's orders.

        Args:
            ticker: Optional filter by ticker
            status: Optional filter by status (e.g., "open", "filled", "canceled")

        Returns:
            List of order dictionaries
        """
        params = {}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status

        response = await self._request("GET", "/portfolio/orders", params=params)
        # API wraps response in {"orders": [...]}
        if isinstance(response, dict):
            return response.get("orders", response)
        return response

    async def get_positions(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get user's positions.

        Args:
            ticker: Optional filter by ticker

        Returns:
            List of position dictionaries
        """
        params = {}
        if ticker:
            params["ticker"] = ticker

        response = await self._request("GET", "/portfolio/positions", params=params)
        # API wraps response in {"market_positions": [...]}
        if isinstance(response, dict):
            return response.get("market_positions", response.get("positions", response))
        return response

    async def get_balance(self) -> Dict[str, Any]:
        """
        Get account balance.

        Returns:
            Balance dictionary with balance amount
        """
        return await self._request("GET", "/portfolio/balance")

    async def get_fills(
        self, ticker: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get user's fills/trades.

        Args:
            ticker: Optional filter by ticker
            limit: Maximum fills to return

        Returns:
            List of fill dictionaries
        """
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker

        response = await self._request("GET", "/portfolio/fills", params=params)
        # API wraps response in {"fills": [...]}
        if isinstance(response, dict):
            return response.get("fills", response)
        return response

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
        logger.debug("Closed KalshiClient")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
