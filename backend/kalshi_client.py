from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from types import SimpleNamespace
from typing import Optional
import requests
import base64
import time
import uuid
from utils import retry_on_api_error
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    kalshi_api_key: str
    kalshi_private_key_path: str
    kalshi_host: str = "https://api.elections.kalshi.com"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


class KalshiTrader:
    def __init__(self):
        settings = Settings()  # type: ignore[call-arg]
        
        with open(settings.kalshi_private_key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("Private key must be RSA")
        
        self.private_key: rsa.RSAPrivateKey = key
        self.api_key = settings.kalshi_api_key
        self.base_url = settings.kalshi_host
        self.session = requests.Session()
    
    def _sign_request(self, timestamp: str, method: str, path: str) -> str:
        """Create PSS signature for request authentication."""
        path_without_query = path.split('?')[0]
        message = f"{timestamp}{method}{path_without_query}".encode("utf-8")
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode("utf-8")
    
    def _create_auth(self, method: str, path: str) -> tuple[str, str]:
        """Create authentication timestamp and signature."""
        timestamp = str(int(time.time() * 1000))
        signature = self._sign_request(timestamp, method, path)
        return timestamp, signature
    
    @retry_on_api_error(max_retries=3, backoff_seconds=2)
    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make authenticated request to Kalshi API."""
        timestamp, signature = self._create_auth(method, f"/trade-api/v2{path}")
        headers = {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }
        
        response = self.session.request(
            method, f"{self.base_url}/trade-api/v2{path}", headers=headers, timeout=30, **kwargs
        )
        if not response.ok:
            body = (response.text or "")[:500]
            logger.error(f"Kalshi {method} {path} -> {response.status_code}: {body}")
            response.raise_for_status()
        # 201 create-order returns a body; some deletes may be empty
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()
    
    def get_balance(self) -> dict:
        """Get account balance and portfolio value (always in dollars)."""
        data = self._request("GET", "/portfolio/balance")

        if "balance_dollars" in data:
            balance = float(data["balance_dollars"])
        else:
            balance = data.get("balance", 0) / 100

        if "portfolio_value_dollars" in data:
            portfolio_value = float(data["portfolio_value_dollars"])
        else:
            # Legacy portfolio_value is integer cents
            portfolio_value = data.get("portfolio_value", 0) / 100

        return {
            "balance": balance,
            "portfolio_value": portfolio_value,
            "updated_ts": data.get("updated_ts", 0),
        }
    
    def get_markets(self, tickers: Optional[list] = None, status: str = "open", 
                    max_close_ts: Optional[int] = None) -> list:
        """Fetch all markets matching criteria."""
        all_markets = []
        cursor = None
        
        while True:
            params = {"status": status, "limit": 1000}
            if max_close_ts:
                params["max_close_ts"] = max_close_ts
            if tickers:
                params["tickers"] = ",".join(tickers)
            if cursor:
                params["cursor"] = cursor
            
            data = self._request("GET", "/markets", params=params)
            all_markets.extend(SimpleNamespace(**m) for m in data.get("markets", []))
            
            cursor = data.get("cursor")
            if not cursor:
                break
        
        return all_markets
    
    def get_positions(self):
        """Get current positions."""
        data = self._request("GET", "/portfolio/positions", params={
            "limit": 1000,
            "count_filter": "position"
        })
        if "market_positions" in data:
            data["market_positions"] = [SimpleNamespace(**pos) for pos in data["market_positions"]]
        return SimpleNamespace(**data)

    @staticmethod
    def _dollars(cents: int) -> str:
        """Format integer cents as FixedPointDollars (4dp), clamped to [1¢, 99¢]."""
        cents = max(1, min(99, int(cents)))
        return f"{cents / 100:.4f}"

    @staticmethod
    def _count_fp(quantity: int | float) -> str:
        q = max(0.01, float(quantity))
        return f"{q:.2f}"

    def _yes_book_order(self, side: str, price_cents: int) -> tuple[str, str]:
        """
        Map legacy yes/no + cents to V2 YES-book side + dollar price.
        bid = buy YES; ask = sell YES (= buy NO at 1 - price).
        """
        if side == "yes":
            return "bid", self._dollars(price_cents)
        # Buy NO @ P ⇔ sell YES @ (100 - P)
        return "ask", self._dollars(100 - price_cents)

    def create_order(self, ticker: str, side: str, quantity: int, price: int):
        """
        Buy contracts on the V2 events-orders endpoint.
        `side` is still 'yes'/'no'; `price` is integer cents (legacy call sites).
        """
        book_side, price_dollars = self._yes_book_order(side, price)
        payload = {
            "ticker": ticker,
            "side": book_side,
            "count": self._count_fp(quantity),
            "price": price_dollars,
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": str(uuid.uuid4()),
        }
        logger.info(f"Creating V2 order payload: {payload} (contract_side={side})")
        try:
            return self._request("POST", "/portfolio/events/orders", json=payload)
        except Exception as e:
            logger.error(f"Create order API error. Payload: {payload}, Error: {e}")
            raise

    def close_position(self, ticker: str, side: str, quantity: int,
                       price: Optional[int] = None, order_type: str = "limit"):
        """
        Close a yes/no position via V2 YES-book orders.

        Holding YES → sell YES (ask) at yes bid.
        Holding NO  → sell NO ⇔ buy YES (bid) at 1 - no_bid.

        Do NOT set reduce_only: for NO positions the close is a YES bid, and
        reduce_only is defined against long YES size — it caps count to 0 and
        Kalshi returns HTTP 400.
        """
        qty = max(1, int(round(float(quantity))))

        if order_type == "market" or price is None:
            # Cross the book with IOC at an aggressive but valid price
            if side == "yes":
                book_side, price_dollars = "ask", "0.0100"
            else:
                book_side, price_dollars = "bid", "0.9900"
            tif = "immediate_or_cancel"
        else:
            px = max(1, min(99, int(price)))
            if side == "yes":
                # Sell YES at the YES bid
                book_side, price_dollars = "ask", self._dollars(px)
            else:
                # Sell NO at NO bid P ⇔ buy YES at (100 - P)
                book_side, price_dollars = "bid", self._dollars(100 - px)
            tif = "good_till_canceled"

        payload = {
            "ticker": ticker,
            "side": book_side,
            "count": self._count_fp(qty),
            "price": price_dollars,
            "time_in_force": tif,
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": str(uuid.uuid4()),
        }
        logger.info(f"Closing V2 order payload: {payload} (position_side={side})")
        return self._request("POST", "/portfolio/events/orders", json=payload)

    def get_orders(self, status: str = "resting") -> list:
        """Get orders by status."""
        all_orders = []
        cursor = None
        
        while True:
            params = {"status": status, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            
            data = self._request("GET", "/portfolio/orders", params=params)
            all_orders.extend(SimpleNamespace(**o) for o in data.get("orders", []))
            
            cursor = data.get("cursor")
            if not cursor:
                break
        
        return all_orders

    def cancel_order(self, order_id: str):
        """Cancel a pending order (V2 events path, with legacy fallback)."""
        try:
            return self._request("DELETE", f"/portfolio/events/orders/{order_id}")
        except Exception as e:
            logger.warning(f"V2 cancel failed for {order_id} ({e}); trying legacy path")
            return self._request("DELETE", f"/portfolio/orders/{order_id}")
