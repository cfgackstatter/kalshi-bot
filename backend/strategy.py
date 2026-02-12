from datetime import datetime, timezone, timedelta
from kalshi_client import KalshiTrader
from utils import parse_datetime
from typing import Optional
import math
import logging

logger = logging.getLogger(__name__)

def calculate_kelly_position(order_price: int, estimated_edge: float, total_portfolio: float,
                            kelly_fraction: float = 0.25, max_position_pct: float = 0.05) -> float:
    """
    Calculate Kelly-based position size for high-probability bets.
    
    Args:
        order_price: Entry price in cents (e.g., 97)
        estimated_edge: Your estimated edge in probability (e.g., 0.02 for 2%)
        total_portfolio: Total portfolio value in dollars
        kelly_fraction: Fraction of full Kelly to use (0.25 = quarter Kelly for safety)
        max_position_pct: Maximum position as % of portfolio (0.05 = 5%)
    
    Returns:
        Position capital in dollars
    """
    implied_prob = order_price / 100
    
    # Kelly formula for binary outcome: edge / odds
    # For high-prob bets, odds = (1 - implied_prob)
    if implied_prob >= 0.99:
        # For 99%+ bets, cap Kelly aggressively
        kelly = estimated_edge / 0.01  # Minimum 1% odds
    else:
        kelly = estimated_edge / (1 - implied_prob)
    
    # Apply fractional Kelly and portfolio cap
    safe_kelly = min(kelly * kelly_fraction, max_position_pct)
    
    # Ensure minimum position size if edge exists
    position_capital = total_portfolio * max(safe_kelly, 0.005)  # Minimum 0.5%
    
    return position_capital


class HighProbStrategy:
    def __init__(self, trader: KalshiTrader, config: dict):
        self.trader = trader
        self.config = config
        self.monitored_markets = {}
        self.held_positions = {}
        self.stop_loss_attempts = {}
        self.buy_attempts = {}

    # ============================================================================
    # Public Methods - Called by main.py
    # ============================================================================

    def scan_markets(self):
        """Periodic scan to find eligible markets based on time/price filters."""
        markets = self._fetch_eligible_markets()
        eligible_tickers = []
        for market in markets:
            if self._passes_basic_filters(market):
                eligible_tickers.append(market.ticker)
                self.monitored_markets[market.ticker] = market
        logger.info(f"Scan: {len(eligible_tickers)} eligible markets")
        return eligible_tickers

    def update_positions(self):
        """Update held positions from API."""
        positions_response = self.trader.get_positions()
        market_positions = getattr(positions_response, "market_positions", [])
        self.held_positions = {}
        for pos in market_positions:
            self.held_positions[pos.ticker] = {
                "side": "yes" if pos.position > 0 else "no",
                "contracts": abs(pos.position),
            }

    def update_ticker_price(self, ticker_data: dict):
        """WebSocket callback - check buying opportunity or exit conditions."""
        ticker = ticker_data.get("market_ticker")
        if not ticker:
            return
        
        prices = self._parse_ticker_prices(ticker_data)
        
        if ticker in self.held_positions:
            self._check_exit_conditions(ticker, prices)
        elif ticker in self.monitored_markets:
            self._check_buying_opportunity(ticker, prices)

    def cleanup_pending_orders(self):
        """Cancel orders older than max_pending_age_minutes."""
        max_age = self.config.get("max_pending_age_minutes", 5)
        try:
            pending = self.trader.get_orders(status="resting")
            if not pending:
                return
            
            now = datetime.now(timezone.utc)
            for order in pending:
                try:
                    created = parse_datetime(order.created_time)
                    age_minutes = (now - created).total_seconds() / 60
                    if age_minutes > max_age:
                        self.trader.cancel_order(order.order_id)
                        logger.info(f"Cancelled stale order: {order.ticker}")
                except Exception as e:
                    logger.error(f"Failed to cancel order {order.order_id}: {e}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    # ============================================================================
    # Private Methods - Internal Strategy Logic
    # ============================================================================

    def _fetch_eligible_markets(self):
        """Fetch markets within time window."""
        now = datetime.now(timezone.utc)
        max_close_time = now + timedelta(hours=self.config["max_time_to_expiry"])
        return self.trader.get_markets(status="open", max_close_ts=int(max_close_time.timestamp()))

    def _passes_basic_filters(self, market) -> bool:
        """Apply ticker exclusions, liquidity, and volume filters."""
        exclude_substrings = self.config.get("ticker_exclude_substrings", "")
        if exclude_substrings:
            exclusions = [s.strip().lower() for s in exclude_substrings.split(",") if s.strip()]
            if any(excl in market.ticker.lower() for excl in exclusions):
                return False
        
        yes_bid = int(float(getattr(market, "yes_bid_dollars", "0")) * 100)
        yes_ask = int(float(getattr(market, "yes_ask_dollars", "0")) * 100)
        no_bid = int(float(getattr(market, "no_bid_dollars", "0")) * 100)
        no_ask = int(float(getattr(market, "no_ask_dollars", "0")) * 100)
        
        return not ((yes_bid == 0 and yes_ask == 100) or (no_bid == 0 and no_ask == 100)) and (getattr(market, "volume", 0) or 0) > 0

    def _parse_ticker_prices(self, ticker_data: dict) -> dict:
        """Extract prices from WebSocket ticker data."""
        return {
            "yes_bid": int(float(ticker_data.get("yes_bid_dollars", "0")) * 100),
            "yes_ask": int(float(ticker_data.get("yes_ask_dollars", "0")) * 100),
            "no_bid": int(float(ticker_data.get("no_bid_dollars", "0")) * 100),
            "no_ask": int(float(ticker_data.get("no_ask_dollars", "0")) * 100),
        }

    def _check_exit_conditions(self, ticker: str, prices: dict):
        """Check if position should be closed due to take-profit or stop-loss."""
        position = self.held_positions[ticker]
        side = position["side"]
        
        bid = prices[f"{side}_bid"]
        ask = prices[f"{side}_ask"]
        spread = ask - bid
        mid = (bid + ask) / 2
        
        # Get entry price for percentage-based stop-loss
        entry_price = position.get("entry_price", mid)
        
        # Take-profit: Only exit if we have meaningful profit
        if bid >= 100:
            # Maximum price reached - always sell
            logger.info(f"TAKE-PROFIT (100¢ bid): {ticker} {side}")
            self._close_position(ticker, position, prices)
            return
        
        # Exit at 99¢ ONLY if we have at least 1¢ profit
        if bid >= 99 and entry_price <= 98:
            profit = bid - entry_price
            logger.info(f"TAKE-PROFIT: {ticker} {side} bid={bid}¢ entry={entry_price}¢ profit={+profit}¢")
            self._close_position(ticker, position, prices)
            return
        
        # Percentage-based stop-loss (default 30% loss)
        max_loss_pct = self.config.get("max_loss_percent", 0.30)
        stop_loss_price = entry_price * (1 - max_loss_pct)
        
        if mid < stop_loss_price:
            loss_pct = ((entry_price - mid) / entry_price) * 100
            logger.warning(
                f"STOP-LOSS triggered: {ticker} {side} "
                f"entry={entry_price}¢ mid={mid:.1f}¢ loss={loss_pct:.1f}% spread={spread}¢"
            )
            self._close_position(ticker, position, prices)
            return
        
        # Additional emergency exit for wide spreads (market going illiquid)
        if spread >= 50 and mid < entry_price * 0.85:
            logger.error(
                f"EMERGENCY EXIT (illiquid): {ticker} {side} "
                f"mid={mid:.1f}¢ spread={spread}¢"
            )
            self._close_position(ticker, position, prices, emergency=True)

    def _check_buying_opportunity(self, ticker: str, prices: dict):
        """Check if market meets all buying criteria."""
        markets = self.trader.get_markets(tickers=[ticker])
        if not markets:
            return
        market = markets[0]
        
        for side in ["yes", "no"]:
            if self._should_buy(ticker, side, prices, market):
                self._execute_buy(ticker, side, prices, market)

    def _should_buy(self, ticker: str, side: str, prices: dict, market) -> bool:
        """Apply all buying criteria."""
        bid = prices[f"{side}_bid"]
        ask = prices[f"{side}_ask"]
        
        # Check spread
        spread = ask - bid
        if spread > self.config.get("max_spread", 99):
            return False
        
        # Check minimum probability using mid
        mid = (bid + ask) / 2
        if mid < self.config["min_probability"]:
            return False
        
        # Check volume
        volume = getattr(market, "volume", 0) or 0
        if volume < self.config.get("min_volume", 0):
            return False
        
        # Check if already held
        if ticker in self.held_positions:
            return False
        
        return True

    def _execute_buy(self, ticker: str, side: str, prices: dict, market):
        """Execute buy order with Kelly-based position sizing."""
        now = datetime.now(timezone.utc)
        last_attempt = self.buy_attempts.get(ticker)
        if last_attempt and (now - last_attempt).total_seconds() < 10:
            return
        
        bid = prices[f"{side}_bid"]
        ask = prices[f"{side}_ask"]
        
        # Order price strategy: bid for maker, bid+1 for faster fill
        if self.config.get("order_at_bid", False):
            order_price = max(bid, 1)
        else:
            order_price = min(bid + 1, 98)
        
        balance_data = self.trader.get_balance()
        total_portfolio = balance_data["balance"] + balance_data["portfolio_value"]
        available_cash = balance_data["balance"]
        
        # Kelly-based position sizing
        estimated_edge = self.config.get("estimated_edge", 0.02)
        kelly_fraction = self.config.get("kelly_fraction", 0.25)
        max_position_pct = self.config.get("max_position_pct", 0.05)
        
        position_capital = calculate_kelly_position(
            order_price=order_price,
            estimated_edge=estimated_edge,
            total_portfolio=total_portfolio,
            kelly_fraction=kelly_fraction,
            max_position_pct=max_position_pct
        )
        
        entry_price = order_price / 100
        
        # INTEGER CONTRACT CALCULATION: Round to nearest integer, minimum 1
        desired_contracts = max(1, round(position_capital / entry_price))
        
        # Cap by available cash (also integer)
        max_affordable_contracts = max(0, int(available_cash / entry_price))
        contracts = min(desired_contracts, max_affordable_contracts)
        
        if contracts < 1:
            return
        
        self.buy_attempts[ticker] = now
        
        try:
            total_cost = contracts * entry_price
            self.trader.create_order(
                ticker=ticker,
                side=side,
                quantity=contracts,
                price=order_price
            )
            
            # Store entry price for stop-loss calculation
            self.held_positions[ticker] = {
                "side": side,
                "contracts": contracts,
                "entry_price": order_price,
                "entry_time": now.isoformat()
            }
            
            self.monitored_markets.pop(ticker, None)
            self.buy_attempts.pop(ticker, None)
            
            logger.info(
                f"BUY {contracts} {side} @ {order_price}¢ on {ticker} "
                f"(cost: ${total_cost:.2f}, kelly_size: ${position_capital:.2f})"
            )
        except Exception as e:
            logger.error(f"Buy order failed for {ticker}: {e}")

    def _close_position(self, ticker: str, position: dict, prices: Optional[dict] = None, emergency: bool = False):
        """
        Close position at best available price.
        
        Args:
            ticker: Market ticker
            position: Position dict with side, contracts, entry_price
            prices: Current prices dict (if available from WebSocket)
            emergency: If True, use market order for immediate exit
        """
        try:
            side = position["side"]
            
            # Get fresh market data if prices not provided
            if prices is None:
                markets = self.trader.get_markets(tickers=[ticker])
                if not markets:
                    logger.error(f"Cannot fetch market data for {ticker}, attempting emergency exit")
                    emergency = True
                    bid, ask, spread = 0, 0, 100
                else:
                    market = markets[0]
                    bid = int(float(getattr(market, f"{side}_bid_dollars", "0")) * 100)
                    ask = int(float(getattr(market, f"{side}_ask_dollars", "0")) * 100)
                    spread = ask - bid
            else:
                bid = prices[f"{side}_bid"]
                ask = prices[f"{side}_ask"]
                spread = ask - bid
            
            # Determine exit strategy
            if emergency or spread >= 50:
                order_type = "market"
                exit_price = None
                logger.warning(
                    f"Using MARKET ORDER for {ticker} (spread={spread}¢, emergency={emergency})"
                )
            elif bid >= 1:
                order_type = "limit"
                exit_price = bid
            else:
                order_type = "limit"
                exit_price = 1
                logger.warning(f"Bid collapsed for {ticker}, attempting 1¢ exit")
            
            # Execute close order
            self.trader.close_position(
                ticker=ticker,
                side=side,
                quantity=position["contracts"],
                price=exit_price,
                order_type=order_type
            )
            
            # Calculate P&L if entry_price available
            entry_price = position.get("entry_price")
            if entry_price and exit_price:
                pnl_per_contract = exit_price - entry_price
                total_pnl = pnl_per_contract * position["contracts"] / 100
                pnl_pct = (pnl_per_contract / entry_price) * 100
                logger.info(
                    f"CLOSED {position['contracts']} {side} on {ticker} @ {exit_price}¢ "
                    f"(entry={entry_price}¢, P&L=${total_pnl:.2f}, {pnl_pct:+.1f}%)"
                )
            else:
                logger.info(
                    f"CLOSED {position['contracts']} {side} on {ticker} "
                    f"@ {'MARKET' if order_type == 'market' else f'{exit_price}¢'}"
                )
            
            # Remove position tracking
            self.held_positions.pop(ticker, None)
            self.stop_loss_attempts.pop(ticker, None)
            
        except Exception as e:
            logger.error(f"Position close failed for {ticker}: {e}")
