from datetime import datetime, timedelta, timezone
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
            print("Strategy scanning markets...")
            markets_response = self.trader.get_markets(status="open", limit=200)
            
            # Handle the response object correctly
            if not hasattr(markets_response, 'markets'):
                print(f"Unexpected response format: {type(markets_response)}")
                return
            
            opportunities = []
            now = datetime.now(timezone.utc)
            
            for market in markets_response.markets:
                # Parse the close time
                if hasattr(market, 'close_time'):
                    close_time_str = market.close_time
                    if isinstance(close_time_str, str):
                        close_time_str = close_time_str.replace('Z', '+00:00')
                        close_time = datetime.fromisoformat(close_time_str)
                    else:
                        close_time = close_time_str
                    
                    days_to_close = (close_time - now).days
                    
                    if days_to_close > self.params["max_time_to_close"] or days_to_close < 0:
                        continue
                    
                    # Check if market has yes_price
                    if hasattr(market, 'yes_bid') and market.yes_bid:
                        prob = market.yes_bid / 100
                        if prob >= self.params["min_probability"]:
                            kelly = self.kelly_size(prob, market.yes_bid)
                            size = int(self.params["position_size"] * kelly)
                            
                            if size > 0:
                                opportunities.append({
                                    "ticker": market.ticker,
                                    "prob": prob,
                                    "size": size,
                                    "days": days_to_close
                                })
            
            print(f"Found {len(opportunities)} opportunities")
            
            # Execute top 5 opportunities
            for opp in opportunities[:5]:
                print(f"Executing trade: {opp}")
                self.execute_trade(opp)
                
        except Exception as e:
            print(f"Strategy error: {e}")
            import traceback
            traceback.print_exc()
    
    def execute_trade(self, opp: dict):
        try:
            order = self.trader.place_order(
                ticker=opp["ticker"],
                action="buy",
                side="yes",
                count=opp["size"]
            )
            self.db.save_trade(opp, order)
            print(f"Trade executed: {opp['ticker']}")
        except Exception as e:
            print(f"Trade execution error: {e}")
