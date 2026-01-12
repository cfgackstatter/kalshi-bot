from datetime import datetime, timezone, timedelta
from kalshi_client import KalshiTrader

class HighProbStrategy:
    def __init__(self, trader: KalshiTrader, config: dict):
        self.trader = trader
        self.config = config
        
    def scan_and_execute(self):
        """Main strategy execution cycle."""
        balance = self.trader.get_balance()["balance"]
        allocated_capital = balance * (self.config["capital_allocation"] / 100)
        position_capital = allocated_capital * (self.config["position_size"] / 100)
        
        # Get existing positions to avoid duplicates
        existing_positions = self._get_existing_tickers()
        
        # Get candidate markets
        now = datetime.now(timezone.utc)
        max_close_time = now + timedelta(hours=self.config["max_time_to_expiry"])
        markets = self.trader.get_markets(status="open", max_close_ts=int(max_close_time.timestamp()))
        
        # Filter and rank opportunities
        opportunities = []
        for market in markets:
            if market.ticker in existing_positions:
                continue  # Skip if already holding position
            
            opp = self._evaluate_market(market, position_capital)
            if opp and opp["yield"] > 0:
                opportunities.append(opp)
        
        # Sort by yield (highest first)
        opportunities.sort(key=lambda x: x["yield"], reverse=True)
        
        # Execute trades
        capital_used = 0
        for opp in opportunities:
            remaining = allocated_capital - capital_used
            if remaining < position_capital:
                break
            
            if opp["contracts"] < 2:  # Skip if less than 2 contracts
                continue
            
            try:
                self.trader.create_order(
                    ticker=opp["ticker"],
                    side=opp["side"],
                    quantity=opp["contracts"],
                    price=opp["price"]
                )
                capital_used += opp["contracts"] * (opp["price"] / 100)
                print(f"Ordered {opp['contracts']} {opp['side']} @ {opp['price']}¢ on {opp['ticker']}")
            except Exception as e:
                print(f"Order failed for {opp['ticker']}: {e}")
    
    def check_exits(self):
        """Monitor positions for stop-loss exits."""
        positions_response = self.trader.get_positions()
        market_positions = getattr(positions_response, "market_positions", [])
        
        if not market_positions:
            return
        
        tickers = [pos.ticker for pos in market_positions]
        markets = self.trader.get_markets(tickers=tickers)
        markets_dict = {m.ticker: m for m in markets}
        
        for pos in market_positions:
            market = markets_dict.get(pos.ticker)
            if not market:
                continue
            
            # Determine position side (positive = yes, negative = no)
            contracts = pos.position
            side = "yes" if contracts > 0 else "no"
            contracts = abs(contracts)
            
            # Check appropriate bid for stop-loss
            current_bid = market.yes_bid if side == "yes" else market.no_bid
            
            if current_bid <= self.config["stop_loss"]:
                try:
                    self.trader.close_position(
                        ticker=pos.ticker,
                        side=side,
                        quantity=contracts,
                        price=current_bid
                    )
                    print(f"Stop-loss triggered: closed {contracts} {side} @ {current_bid}¢ on {pos.ticker}")
                except Exception as e:
                    print(f"Exit failed for {pos.ticker}: {e}")
    
    def _get_existing_tickers(self) -> set:
        """Get set of tickers we already have positions in."""
        positions_response = self.trader.get_positions()
        market_positions = getattr(positions_response, "market_positions", [])
        return {pos.ticker for pos in market_positions}
    
    def _evaluate_market(self, market, position_capital: float) -> dict:
        """Evaluate market and return opportunity dict if valid."""
        yes_bid = getattr(market, "yes_bid", 0)
        yes_ask = getattr(market, "yes_ask", 0)
        no_bid = getattr(market, "no_bid", 0)
        no_ask = getattr(market, "no_ask", 0)
        
        # Check both YES and NO sides
        yes_opportunity = self._calculate_opportunity(
            market, "yes", yes_bid, yes_ask, position_capital
        )
        no_opportunity = self._calculate_opportunity(
            market, "no", no_bid, no_ask, position_capital
        )
        
        # Return the better opportunity
        if yes_opportunity and no_opportunity:
            return yes_opportunity if yes_opportunity["yield"] > no_opportunity["yield"] else no_opportunity
        return yes_opportunity or no_opportunity
    
    def _calculate_opportunity(self, market, side: str, bid: int, ask: int, position_capital: float):
        """Calculate yield for one side of market."""
        if bid < self.config["min_probability"]:
            return None
        if ask >= 100 or ask <= 0:
            return None
        
        # Calculate contracts we would buy
        entry_price = ask / 100
        contracts = int(position_capital / entry_price)
        
        if contracts < 2:
            return None
        
        # Calculate fees based on actual position size
        # Kalshi: 7¢ settlement + trading fee (varies, using 0 for maker)
        total_fees = contracts * 0.07
        
        # Calculate profit
        total_cost = contracts * entry_price
        payout_if_right = contracts * 1.0
        net_profit = payout_if_right - total_cost - total_fees
        
        if net_profit <= 0:
            return None
        
        # Calculate annualized yield
        close_time = market.close_time
        if isinstance(close_time, str):
            close_time = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        
        hours_to_expiry = (close_time - datetime.now(timezone.utc)).total_seconds() / 3600
        
        if hours_to_expiry <= 0:
            return None
        
        annualized_yield = (net_profit / total_cost) * (8760 / hours_to_expiry)
        
        return {
            "ticker": market.ticker,
            "side": side,
            "price": ask,
            "contracts": contracts,
            "yield": annualized_yield,
            "net_profit": net_profit
        }
