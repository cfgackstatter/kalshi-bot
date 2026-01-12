from datetime import datetime, timezone, timedelta
from time import sleep
from kalshi_client import KalshiTrader

class HighProbStrategy:
    def __init__(self, trader: KalshiTrader, config: dict):
        self.trader = trader
        self.config = config
        
    def scan_and_execute(self):
        """Main strategy execution with iterative best-opportunity selection."""
        print("=== Starting strategy scan ===")
        
        # Clean up stale pending orders first
        self._cleanup_pending_orders()
        
        # Fetch and evaluate all markets once
        markets = self._fetch_markets()
        all_opportunities = self._evaluate_all_markets(markets)
        
        if not all_opportunities:
            print("No eligible opportunities found")
            return
        
        # Sort by yield once (descending)
        all_opportunities.sort(key=lambda x: x["yield"], reverse=True)
        print(f"Found {len(all_opportunities)} eligible opportunities")
        
        # Iteratively place orders for best opportunities
        orders_placed = 0
        max_iterations = 50
        
        for iteration in range(max_iterations):
            # Refresh state
            state = self._get_current_state()
            
            # Check exit conditions
            if not self._can_place_order(state):
                print(f"Exit: {state['exit_reason']}")
                break
            
            # Filter to opportunities not already held
            eligible = [
                opp for opp in all_opportunities 
                if opp["ticker"] not in state["held_tickers"]
            ]
            
            if not eligible:
                print("Exit: No more eligible opportunities")
                break
            
            # Take best opportunity
            best = eligible[0]
            
            # Place order
            if self._place_order(best):
                orders_placed += 1
                print(f"[{iteration+1}] Ordered {best['contracts']} {best['side']} @ {best['price']}¢ on {best['ticker']} (yield: {best['yield']:.1f}%)")
            
            # Brief pause for order processing
            sleep(self.config.get("order_delay_seconds", 2))
        
        print(f"=== Scan complete: {orders_placed} orders placed ===")
    
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
            
            contracts = pos.position
            side = "yes" if contracts > 0 else "no"
            contracts = abs(contracts)
            current_bid = market.yes_bid if side == "yes" else market.no_bid
            
            if current_bid <= self.config["stop_loss"]:
                try:
                    self.trader.close_position(
                        ticker=pos.ticker,
                        side=side,
                        quantity=contracts,
                        price=current_bid
                    )
                    print(f"Stop-loss: closed {contracts} {side} @ {current_bid}¢ on {pos.ticker}")
                except Exception as e:
                    print(f"Exit failed for {pos.ticker}: {e}")
    
    def _cleanup_pending_orders(self):
        """Cancel orders older than max_age_minutes."""
        max_age = self.config.get("max_pending_age_minutes", 5)
        try:
            pending = self.trader.get_pending_orders()
            if not pending:
                return
            
            now = datetime.now(timezone.utc)
            for order in pending:
                created = order.created_time
                if isinstance(created, str):
                    created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                
                age_minutes = (now - created).total_seconds() / 60
                if age_minutes > max_age:
                    self.trader.cancel_order(order.order_id)
                    print(f"Cancelled stale order: {order.ticker} (age: {age_minutes:.1f}min)")
        except Exception as e:
            print(f"Cleanup failed: {e}")
    
    def _fetch_markets(self):
        """Fetch all eligible markets."""
        now = datetime.now(timezone.utc)
        max_close_time = now + timedelta(hours=self.config["max_time_to_expiry"])
        return self.trader.get_markets(status="open", max_close_ts=int(max_close_time.timestamp()))
    
    def _evaluate_all_markets(self, markets):
        """Evaluate all markets and return list of opportunities."""
        opportunities = []
        for market in markets:
            # Evaluate both YES and NO sides
            for side in ["yes", "no"]:
                opp = self._evaluate_side(market, side)
                if opp:
                    opportunities.append(opp)
        return opportunities
    
    def _evaluate_side(self, market, side: str):
        """Evaluate one side of market."""
        bid = getattr(market, f"{side}_bid", 0)
        ask = getattr(market, f"{side}_ask", 0)
        
        # Check minimum probability
        if bid < self.config["min_probability"]:
            return None
        
        # Check valid ask
        if ask >= 100 or ask <= 0:
            return None
        
        # Calculate optimal order price (ask + 1, capped at 99)
        order_price = min(ask + 1, 99)
        
        # Calculate contracts based on position size
        balance = self.trader.get_balance()["balance"]
        allocated_capital = balance * (self.config["capital_allocation"] / 100)
        position_capital = allocated_capital * (self.config["position_size"] / 100)
        
        entry_price = order_price / 100
        contracts = int(position_capital / entry_price)
        
        if contracts < 2:
            return None
        
        # Calculate yield
        total_cost = contracts * entry_price
        total_fees = contracts * 0.07  # Settlement fee
        payout = contracts * 1.0
        net_profit = payout - total_cost - total_fees
        
        if net_profit <= 0:
            return None
        
        # Calculate hours to expiry
        close_time = market.close_time
        if isinstance(close_time, str):
            close_time = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        
        hours = (close_time - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours <= 0:
            return None
        
        annualized_yield = (net_profit / total_cost) * (8760 / hours) * 100
        
        return {
            "ticker": market.ticker,
            "side": side,
            "price": order_price,
            "contracts": contracts,
            "yield": annualized_yield,
            "cost": total_cost
        }
    
    def _get_current_state(self):
        """Get current portfolio state."""
        balance = self.trader.get_balance()["balance"]
        positions_response = self.trader.get_positions()
        pending_orders = self.trader.get_pending_orders()
        
        market_positions = getattr(positions_response, "market_positions", [])
        
        # Calculate used capital
        positions_value = sum(
            abs(pos.market_exposure_dollars) + abs(pos.fees_paid_dollars)
            for pos in market_positions
        )
        
        pending_value = sum(
            (order.quantity * order.price / 100)
            for order in (pending_orders or [])
        )
        
        # Calculate available capital
        allocated_capital = balance * (self.config["capital_allocation"] / 100)
        used_capital = positions_value + pending_value
        remaining = allocated_capital - used_capital
        position_capital = allocated_capital * (self.config["position_size"] / 100)
        
        # Get held tickers
        held_tickers = {pos.ticker for pos in market_positions}
        held_tickers.update({order.ticker for order in (pending_orders or [])})
        
        # Determine exit reason if can't continue
        exit_reason = None
        if remaining < position_capital:
            exit_reason = "Capital exhausted"
        elif len(market_positions) + len(pending_orders or []) >= self.config.get("max_positions", 20):
            exit_reason = "Max positions reached"
        
        return {
            "remaining_capital": remaining,
            "position_capital": position_capital,
            "held_tickers": held_tickers,
            "exit_reason": exit_reason
        }
    
    def _can_place_order(self, state):
        """Check if we can place another order."""
        return state["exit_reason"] is None and state["remaining_capital"] >= state["position_capital"]
    
    def _place_order(self, opportunity):
        """Place order for opportunity."""
        try:
            self.trader.create_order(
                ticker=opportunity["ticker"],
                side=opportunity["side"],
                quantity=opportunity["contracts"],
                price=opportunity["price"]
            )
            return True
        except Exception as e:
            print(f"Order failed: {e}")
            return False
