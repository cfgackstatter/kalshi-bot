from datetime import datetime, timezone, timedelta
from time import sleep
from kalshi_client import KalshiTrader
import math

class HighProbStrategy:
    def __init__(self, trader: KalshiTrader, config: dict):
        self.trader = trader
        self.config = config

    def scan_and_execute(self):
        """Main strategy execution with iterative best-opportunity selection."""
        print("=== Starting strategy scan ===")
        print(f"Config: {self.config}")

        # Clean up stale pending orders first
        self._cleanup_pending_orders()

        # Get balance and portfolio_value
        balance_data = self.trader.get_balance()
        balance = balance_data["balance"]  # Cash
        positions_value_from_api = balance_data["portfolio_value"]  # Positions value
        total_portfolio = balance + positions_value_from_api

        # Fetch positions and pending orders
        positions_response = self.trader.get_positions()
        pending_orders = self.trader.get_orders(status='resting')
        market_positions = getattr(positions_response, "market_positions", [])

        # Check stop-losses using already-fetched positions
        self._check_stop_losses_with_positions(market_positions)
        
        # Calculate used capital
        positions_value = sum(
            abs(float(pos.market_exposure_dollars)) + abs(float(pos.fees_paid_dollars))
            for pos in market_positions
        )
        
        pending_value = sum(
            (order.remaining_count * getattr(order, f"{order.side}_price", 0) / 100)
            for order in pending_orders
        )

        used_capital = positions_value + pending_value
        allocated_capital = total_portfolio * (self.config["capital_allocation"] / 100)

        # Build set of held tickers
        held_tickers = {pos.ticker for pos in market_positions}
        held_tickers.update({order.ticker for order in pending_orders})

        print(f"Portfolio: cash=${balance:.2f}, positions=${positions_value_from_api:.2f}, total=${total_portfolio:.2f}")
        print(f"Allocated: ${allocated_capital:.2f} ({self.config['capital_allocation']}%)")
        print(f"Used: ${used_capital:.2f}, Available: ${allocated_capital - used_capital:.2f}")

        # Fetch and evaluate all markets once
        markets = self._fetch_markets()
        all_opportunities = self._evaluate_all_markets(markets, total_portfolio)

        if not all_opportunities:
            print("No eligible opportunities found")
            return

        # Sort by yield once (descending)
        all_opportunities.sort(key=lambda x: x["yield"], reverse=True)
        print(f"Found {len(all_opportunities)} eligible opportunities")

        # Iteratively place orders for best opportunities
        orders_placed = 0
        for opportunity in all_opportunities:
            # Check if already held
            if opportunity["ticker"] in held_tickers:
                continue

            # Adjust to available capital
            available = allocated_capital - used_capital
            entry_price = opportunity["price"] / 100
            max_contracts = int(available / entry_price)

            if max_contracts < 1:
                print(f"Exit: Capital exhausted ({used_capital:.2f}/{allocated_capital:.2f})")
                break

            opportunity["contracts"] = min(opportunity["contracts"], max_contracts)
            opportunity["cost"] = opportunity["contracts"] * entry_price

            # Place order
            if self._place_order(opportunity):
                orders_placed += 1
                used_capital += opportunity["cost"]
                held_tickers.add(opportunity["ticker"])
                print(f"[{orders_placed}] Ordered {opportunity['contracts']} {opportunity['side']} "
                      f"@ {opportunity['price']}¢ on {opportunity['ticker']} "
                      f"(yield: {opportunity['yield']:.1f}%)")
                sleep(self.config.get("order_delay_seconds", 0.5))

        print(f"=== Scan complete: {orders_placed} orders placed ===")

    def _cleanup_pending_orders(self):
        """Cancel orders older than max_age_minutes."""
        max_age = self.config.get("max_pending_age_minutes", 5)
        try:
            pending = self.trader.get_orders(status='resting')
            if not pending:
                return

            now = datetime.now(timezone.utc)
            for order in pending:
                created = self._parse_datetime(order.created_time)
                age_minutes = (now - created).total_seconds() / 60

                if age_minutes > max_age:
                    self.trader.cancel_order(order.order_id)
                    print(f"Cancelled stale order: {order.ticker} (age: {age_minutes:.1f}min)")
        except Exception as e:
            print(f"Cleanup failed: {e}")

    def check_stop_losses(self):
        """Check stop-losses on all positions (called by scheduler)."""
        positions_response = self.trader.get_positions()
        market_positions = getattr(positions_response, "market_positions", [])
        self._check_stop_losses_with_positions(market_positions)

    def _check_stop_losses_with_positions(self, market_positions):
        """Internal: Check stop-losses given position list."""
        if not market_positions:
            return

        tickers = [pos.ticker for pos in market_positions]
        markets = self.trader.get_markets(tickers=tickers)
        markets_dict = {m.ticker: m for m in markets}

        for pos in market_positions:
            market = markets_dict.get(pos.ticker)
            if not market:
                continue

            side = "yes" if pos.position > 0 else "no"
            contracts = abs(pos.position)

            bid_dollars = market.yes_bid_dollars if side == "yes" else market.no_bid_dollars
            ask_dollars = market.yes_ask_dollars if side == "yes" else market.no_ask_dollars
            bid = int(float(bid_dollars) * 100)
            ask = int(float(ask_dollars) * 100)
            mid = (bid + ask) / 2

            if mid <= self.config["stop_loss"]:
                try:
                    self.trader.close_position(
                        ticker=pos.ticker,
                        side=side,
                        quantity=contracts,
                        price=bid
                    )
                    print(f"STOP-LOSS: Sold {contracts} {side} @ {bid}¢ on {pos.ticker}")
                except Exception as e:
                    print(f"Stop-loss exit failed for {pos.ticker}: {e}")

    def _fetch_markets(self):
        """Fetch all eligible markets."""
        now = datetime.now(timezone.utc)
        max_close_time = now + timedelta(hours=self.config["max_time_to_expiry"])
        return self.trader.get_markets(status="open", max_close_ts=int(max_close_time.timestamp()))

    def _evaluate_all_markets(self, markets, balance: float):
        """Evaluate all markets and return list of opportunities."""
        opportunities = []
        for market in markets:
            for side in ["yes", "no"]:
                opp = self._evaluate_side(market, side, balance)
                if opp:
                    opportunities.append(opp)
        return opportunities

    def _evaluate_side(self, market, side: str, balance: float):
        """Evaluate one side of market."""
        bid = int(float(getattr(market, f"{side}_bid_dollars", "0")) * 100)
        ask = int(float(getattr(market, f"{side}_ask_dollars", "0")) * 100)

        # Check valid ask
        if ask >= 100 or ask <= 0:
            return None
        
        # Check minimum probability using mid price
        mid = (bid + ask) / 2
        if mid < self.config["min_probability"]:
            return None
        
        # Check spread constraint
        spread = ask - bid
        if spread > self.config.get("max_spread", 99):
            return None

        # Check volume constraint
        volume = getattr(market, "volume", 0) or 0
        if volume < self.config.get("min_volume", 0):
            return None
        
        # Check ticker exclusion filter
        exclude_substrings = self.config.get("ticker_exclude_substrings", "")
        if exclude_substrings:
            # Split by comma, strip whitespace, convert to lowercase
            exclusions = [s.strip().lower() for s in exclude_substrings.split(",") if s.strip()]
            ticker_lower = market.ticker.lower()
            for exclusion in exclusions:
                if exclusion in ticker_lower:
                    return None

        # Use ask for order
        order_price = min(ask, 99)

        # Calculate contracts based on position size
        position_capital = balance * (self.config["position_size"] / 100)
        entry_price = order_price / 100
        contracts = int(position_capital / entry_price)

        # Calculate yield with fee formula: ceil(0.07 * C * P * (1-P))
        total_cost = contracts * entry_price
        total_fees = math.ceil(0.07 * contracts * entry_price * (1 - entry_price) * 100) / 100
        payout = contracts * 1.0
        net_profit = payout - total_cost - total_fees

        if net_profit <= 0:
            return None

        # Calculate annualized yield
        close_time = self._parse_datetime(market.close_time)
        hours_to_close = (close_time - datetime.now(timezone.utc)).total_seconds() / 3600

        # Filter by risk time (close time)
        if hours_to_close <= 0 or hours_to_close > self.config["max_time_to_expiry"]:
            return None

        # Calculate yield using capital lock time (close + settlement)
        settlement_seconds = getattr(market, "settlement_timer_seconds", 0)
        hours_to_settlement = hours_to_close + (settlement_seconds / 3600)

        annualized_yield = (net_profit / total_cost) * (8760 / hours_to_settlement) * 100

        return {
            "ticker": market.ticker,
            "side": side,
            "price": order_price,
            "contracts": contracts,
            "yield": annualized_yield,
            "cost": total_cost
        }

    def _parse_datetime(self, dt):
        """Parse datetime string to timezone-aware datetime."""
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

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