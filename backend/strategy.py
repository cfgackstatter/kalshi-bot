from datetime import datetime, timezone, timedelta
from kalshi_client import KalshiTrader
from utils import parse_datetime
import math
import logging

logger = logging.getLogger(__name__)


class HighProbStrategy:
    def __init__(self, trader: KalshiTrader, config: dict):
        self.trader = trader
        self.config = config
        self.monitored_markets = {}  # {ticker: market_data} for WebSocket monitored tickers
        self.held_positions = {}  # {ticker: {side, contracts}} for positions we own
        self.stop_loss_attempts = {}  # {ticker: last_attempt_time} for cooldown
        self.buy_attempts = {}  # {ticker: last_attempt_time}

    def scan_markets(self):
        """Periodic scan: find eligible markets based on time/price filters only."""
        logger.info("=== Scanning for eligible markets ===")
        
        markets = self._fetch_eligible_markets()
        eligible_tickers = []
        
        for market in markets:
            if self._passes_basic_filters(market):
                eligible_tickers.append(market.ticker)
                self.monitored_markets[market.ticker] = market
        
        logger.info(f"Found {len(eligible_tickers)} eligible markets to monitor")
        return eligible_tickers
    
    def update_positions(self):
        """Update held positions from API."""
        positions_response = self.trader.get_positions()
        market_positions = getattr(positions_response, "market_positions", [])
        
        self.held_positions = {}
        for pos in market_positions:
            self.held_positions[pos.ticker] = {
                "side": "yes" if pos.position > 0 else "no",
                "contracts": abs(pos.position)
            }
        
        logger.info(f"Updated {len(self.held_positions)} positions")

    def update_ticker_price(self, ticker_data: dict):
        """WebSocket callback: check buying opportunity or stop-loss."""
        ticker = ticker_data.get("market_ticker")
        
        if not ticker:
            logger.warning(f"No ticker in WebSocket data: {ticker_data}")
            return
        
        prices = self._parse_ticker_prices(ticker_data)
        
        # Check if we hold this position -> monitor stop-loss
        if ticker in self.held_positions:
            logger.debug(f"Checking stop-loss for position: {ticker}")
            self._check_stop_loss(ticker, prices)
        # Check if it's a monitored market -> check buying opportunity
        elif ticker in self.monitored_markets:
            logger.debug(f"Checking buying opportunity for: {ticker}")
            self._check_buying_opportunity(ticker, prices)
        else:
            logger.debug(f"Ticker {ticker} not in positions or monitored markets")

    def _fetch_eligible_markets(self):
        """Fetch markets within time window."""
        now = datetime.now(timezone.utc)
        max_close_time = now + timedelta(hours=self.config["max_time_to_expiry"])
        return self.trader.get_markets(status="open", max_close_ts=int(max_close_time.timestamp()))
    
    def _passes_basic_filters(self, market) -> bool:
        """Apply time and price validity filters only."""
        # Check ticker exclusions
        exclude_substrings = self.config.get("ticker_exclude_substrings", "")
        if exclude_substrings:
            exclusions = [s.strip().lower() for s in exclude_substrings.split(",") if s.strip()]
            ticker_lower = market.ticker.lower()
            if any(excl in ticker_lower for excl in exclusions):
                return False
        
        return True
    
    def _parse_ticker_prices(self, ticker_data: dict) -> dict:
        """Extract prices from WebSocket ticker data."""
        return {
            "yes_bid": int(float(ticker_data.get("yes_bid_dollars", 0)) * 100),
            "yes_ask": int(float(ticker_data.get("yes_ask_dollars", 0)) * 100),
            "no_bid": int(float(ticker_data.get("no_bid_dollars", 0)) * 100),
            "no_ask": int(float(ticker_data.get("no_ask_dollars", 0)) * 100),
        }

    def _check_stop_loss(self, ticker: str, prices: dict):
        """Check if position should be closed due to stop-loss."""
        position = self.held_positions[ticker]
        side = position["side"]
        
        bid = prices[f"{side}_bid"]
        ask = prices[f"{side}_ask"]
        
        spread = ask - bid
        mid = (bid + ask) / 2
        
        # Stop-loss: mid below threshold AND spread reasonable (market is liquid)
        if mid <= self.config["stop_loss"] and spread < 50:
            logger.warning(f"STOP-LOSS triggered: {ticker} {side} @ {mid:.1f}¢ (spread={spread}¢)")
            self._execute_stop_loss(ticker, position)

    def _check_buying_opportunity(self, ticker: str, prices: dict):
        """Check if market meets all buying criteria."""
        market = self.monitored_markets.get(ticker)
        if not market:
            logger.debug(f"Ticker {ticker} not in monitored markets")
            return
        
        # Check both sides
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
        
        # Check minimum probability (using mid)
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
        # Check cooldown (don't retry failed orders more than once per 10 seconds)
        now = datetime.now(timezone.utc)
        last_attempt = self.buy_attempts.get(ticker)
        
        if last_attempt and (now - last_attempt).total_seconds() < 10:
            logger.debug(f"Buy cooldown active for {ticker}")
            return
        
        bid = prices[f"{side}_bid"]
        ask = prices[f"{side}_ask"]
        mid = (bid + ask) / 2
        order_price = min(int(mid), 99)
        
        # Calculate position size
        balance_data = self.trader.get_balance()
        total_portfolio = balance_data["balance"] + balance_data["portfolio_value"]
        position_capital = total_portfolio * (self.config["position_size"] / 100)
        
        entry_price = order_price / 100
        contracts = int(position_capital / entry_price)
        
        if contracts < 1:
            return
        
        # Calculate yield to validate profitability
        if not self._is_profitable(contracts, entry_price, market):
            return
        
        self.buy_attempts[ticker] = now
        
        try:
            self.trader.create_order(
                ticker=ticker,
                side=side,
                quantity=contracts,
                price=order_price
            )
            logger.info(f"BUY: {contracts} {side} @ {order_price}¢ on {ticker}")
            
            # Add to held positions
            self.held_positions[ticker] = {"side": side, "contracts": contracts}
            # Remove from monitored (don't double-buy)
            self.monitored_markets.pop(ticker, None)
            # Clear from cooldown on success
            self.buy_attempts.pop(ticker, None)
            
        except Exception as e:
            logger.error(f"Buy order failed for {ticker}: {e}")
            # Don't remove from monitored - but cooldown prevents spam

    def _is_profitable(self, contracts: int, entry_price: float, market) -> bool:
        """Check if trade would be profitable after fees."""
        total_cost = contracts * entry_price
        total_fees = math.ceil(0.07 * contracts * entry_price * (1 - entry_price) * 100) / 100
        payout = contracts * 1.0
        net_profit = payout - total_cost - total_fees
        return net_profit > 0
    
    def _execute_stop_loss(self, ticker: str, position: dict):
        """Execute stop-loss sell at 1¢ (guaranteed immediate fill)."""
        try:
            self.trader.close_position(
                ticker=ticker,
                side=position["side"],
                quantity=position["contracts"],
                price=1,
                order_type="limit"
            )
            logger.warning(f"STOP-LOSS executed: sold {position['contracts']} {position['side']} on {ticker} @ 1¢")
            self.held_positions.pop(ticker, None)
            # Clear from cooldown on success
            self.stop_loss_attempts.pop(ticker, None)
        except Exception as e:
            logger.error(f"Stop-loss execution failed for {ticker}: {e}")

    def cleanup_pending_orders(self):
        """Cancel orders older than max_age_minutes."""
        max_age = self.config.get("max_pending_age_minutes", 5)
        try:
            pending = self.trader.get_orders(status='resting')
            if not pending:
                return
            
            now = datetime.now(timezone.utc)
            for order in pending:
                try:
                    created = parse_datetime(order.created_time)
                    age_minutes = (now - created).total_seconds() / 60
                    if age_minutes > max_age:
                        self.trader.cancel_order(order.order_id)
                        logger.info(f"Cancelled stale order: {order.ticker} (age: {age_minutes:.1f}min)")
                except Exception as e:
                    logger.error(f"Failed to cancel order {order.order_id}: {e}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            # Don't crash, just log and continue