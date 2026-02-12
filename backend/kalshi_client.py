from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from types import SimpleNamespace
from typing import Optional
import requests
import base64
import time
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
        response.raise_for_status()
        return response.json()
    
    def get_balance(self) -> dict:
        """Get account balance and portfolio value."""
        data = self._request("GET", "/portfolio/balance")
        return {
            "balance": data["balance"] / 100,
            "portfolio_value": data.get("portfolio_value", data["balance"]) / 100,
            "updated_ts": data.get("updated_ts", 0)
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
    
    def create_order(self, ticker: str, side: str, quantity: int, price: int):
        """Create a new order."""
        payload = {
            "ticker": ticker,
            "action": "buy",
            "side": side,
            "count": quantity,
            "type": "limit",
            f"{side}_price": price
        }
        
        logger.info(f"Creating order payload: {payload}")
        
        try:
            result = self._request("POST", "/portfolio/orders", json=payload)
            return result
        except Exception as e:
            logger.error(f"Create order API error. Payload: {payload}, Error: {e}")
            raise
    
    def close_position(self, ticker: str, side: str, quantity: int, price: Optional[int] = None, order_type: str = "limit"):
        """Close an existing position."""
        payload = {
            "ticker": ticker,
            "action": "sell",
            "side": side,
            "count": quantity,
            "type": order_type,
        }
        if order_type == "limit" and price is not None:
            payload[f"{side}_price"] = price
        
        return self._request("POST", "/portfolio/orders", json=payload)

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
        """Cancel a pending order."""
        return self._request("DELETE", f"/portfolio/orders/{order_id}")