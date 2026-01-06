from kalshi_python_sync import KalshiClient
from kalshi_python_sync.configuration import Configuration
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Iterator


class Settings(BaseSettings):
    kalshi_api_key: str
    kalshi_private_key_path: str
    kalshi_host: str = "https://api.elections.kalshi.com/trade-api/v2"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


def get_settings() -> Settings:
    """Load settings from .env file."""
    return Settings()  # type: ignore[call-arg]


class KalshiTrader:
    def __init__(self):
        settings = get_settings()
        with open(settings.kalshi_private_key_path, "r") as f:
            private_key = f.read()
        
        config = Configuration(host=settings.kalshi_host)
        config.api_key_id = settings.kalshi_api_key
        config.private_key_pem = private_key
        
        self.client = KalshiClient(config)
    
    def get_balance(self):
        """Get account balance in dollars."""
        balance = self.client.get_balance()
        return {"balance": balance.balance / 100}
    
    def get_all_markets(
        self, 
        status: str = "open", 
        max_close_ts: Optional[int] = None
    ) -> list:
        """
        Get all markets with automatic pagination.
        
        Args:
            status: Market status filter (default "open")
            max_close_ts: Filter markets closing before this Unix timestamp
            
        Returns:
            List of all markets matching filters
        """
        all_markets = []
        cursor = None
        
        while True:
            params = {"status": status, "limit": 1000}
            if max_close_ts is not None:
                params["max_close_ts"] = max_close_ts
            if cursor:
                params["cursor"] = cursor
            
            response = self.client.get_markets(**params)
            all_markets.extend(response.markets)
            
            # Check if there's a next page
            cursor = getattr(response, "cursor", None)
            if not cursor:
                break
        
        return all_markets
    
    def get_positions(self):
        """Get all current positions."""
        return self.client.get_positions()
    
    def create_order(
        self, 
        ticker: str, 
        side: str, 
        quantity: int, 
        price: Optional[int] = None
    ):
        """
        Create an order (limit or market).
        
        Args:
            ticker: Market ticker
            side: "yes" or "no"
            quantity: Number of contracts
            price: Price in cents (1-99). If None, uses market order
        """
        order_type = "limit" if price is not None else "market"
        
        params = {
            "ticker": ticker,
            "action": "buy",
            "side": side,
            "count": quantity,
            "type": order_type
        }
        
        if price is not None:
            params["yes_price"] = price if side == "yes" else None
            params["no_price"] = price if side == "no" else None
        
        return self.client.create_order(**params)
    
    def close_position(self, ticker: str, side: str, quantity: int):
        """Close a position (sell)."""
        return self.client.create_order(
            ticker=ticker,
            action="sell",
            side=side,
            count=quantity,
            type="market"
        )