from datetime import datetime, timedelta
import math

class PremiumCollector:
    def __init__(self, trader, db):
        self.trader = trader
        self.db = db
        self.params = {
            "min_probability": 0.90,
            "max_time_to_close": 7,
            "position_size": 100.0,
            "kelly_fraction": 0.25
        }
    
    def update_params(self, params: dict):
        self.params.update(params)
    
    def get_params(self):
        return self.params
    
    def kelly_size(self, prob: float, price_cents: int):
        edge = prob - (price_cents / 100)
        if edge <= 0:
            return 0
        kelly_fraction = edge / (1 - prob) if prob < 1 else 0
        return kelly_fraction * self.params["kelly_fraction"]
    
    def run(self):
        try:
            markets = self.trader.get_markets(status="open", limit=200)
            opportunities = []
            
            for market in markets.markets:
                close_time = datetime.fromisoformat(market.close_time.replace('Z', '+00:00'))
                days_to_close = (close_time - datetime.now()).days
                
                if days_to_close > self.params["max_time_to_close"]:
                    continue
                
                if hasattr(market, 'yes_price') and market.yes_price:
                    prob = market.yes_price / 100
                    if prob >= self.params["min_probability"]:
                        kelly = self.kelly_size(prob, market.yes_price)
                        size = int(self.params["position_size"] * kelly)
                        
                        if size > 0:
                            opportunities.append({
                                "ticker": market.ticker,
                                "prob": prob,
                                "size": size,
                                "days": days_to_close
                            })
            
            for opp in opportunities[:5]:
                self.execute_trade(opp)
                
        except Exception as e:
            print(f"Strategy error: {e}")
    
    def execute_trade(self, opp: dict):
        try:
            order = self.trader.place_order(
                ticker=opp["ticker"],
                action="buy",
                side="yes",
                count=opp["size"]
            )
            self.db.save_trade(opp, order)
        except Exception as e:
            print(f"Trade execution error: {e}")
