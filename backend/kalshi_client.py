from kalshi_python_sync import KalshiClient
from kalshi_python_sync.configuration import Configuration
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    kalshi_api_key: str
    kalshi_private_key_path: str
    kalshi_host: str = "https://api.elections.kalshi.com/trade-api/v2"
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()

class KalshiTrader:
    def __init__(self):
        with open(settings.kalshi_private_key_path, "r") as f:
            private_key = f.read()
        
        config = Configuration(host=settings.kalshi_host)
        config.api_key_id = settings.kalshi_api_key
        config.private_key_pem = private_key
        
        self.client = KalshiClient(config)
    
    def get_balance(self):
        balance = self.client.get_balance()
        return {"balance": balance.balance / 100}
    
    def get_markets(self, status="open", limit=100):
        return self.client.get_markets(status=status, limit=limit)
    
    def get_market(self, ticker: str):
        return self.client.get_market(ticker)
    
    def place_order(self, ticker: str, action: str, side: str, count: int):
        return self.client.create_order(
            ticker=ticker,
            action=action,
            side=side,
            count=count,
            type="market"
        )
    
    def get_positions(self):
        return self.client.get_positions()
