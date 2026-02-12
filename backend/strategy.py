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
        self.held_positions = {}  # {ticker: {"side": side, "contracts": contracts}} for positions we own
        self.stop_loss_attempts = {}  # {ticker: last_attempt_time} for cooldown
        self.buy_attempts = {}  # {ticker: last_attempt_time}

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

        # Take-profit: Exit at 100¢ bid to lock in gains
        if bid >= 100:
            logger.info(f"TAKE-PROFIT triggered: {ticker} {side} bid={bid}¢")
            self._close_position(ticker, position)
            return

        # Stop-loss: Trigger if mid drops below threshold
        if mid < self.config["stop_loss"]:
            if spread >= 50:
                logger.warning(f"EMERGENCY STOP-LOSS (wide spread): {ticker} {side} mid={mid:.1f} spread={spread}")
            else:
                logger.warning(f"STOP-LOSS triggered: {ticker} {side} mid={mid:.1f} spread={spread}")

            self._close_position(ticker, position)

    def _check_buying_opportunity(self, ticker: str, prices: dict):
        """Check if market meets all buying criteria."""
        market = self.monitored_markets.get(ticker)
        if not market:
            logger.debug(f"Ticker {ticker} not in monitored markets")
            return

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
        """Execute buy order."""
        now = datetime.now(timezone.utc)
        last_attempt = self.buy_attempts.get(ticker)
        if last_attempt and (now - last_attempt).total_seconds() < 10:
            return

        bid = prices[f"{side}_bid"]
        ask = prices[f"{side}_ask"]

        # Buy at bid+1 for faster fills (still profitable at 96+)
        order_price = min(bid + 1, 98)

        balance_data = self.trader.get_balance()
        total_portfolio = balance_data["balance"] + balance_data["portfolio_value"]
        available_cash = balance_data["balance"]

        # Calculate desired position size based on total portfolio
        position_capital = total_portfolio * (self.config["position_size"] / 100)
        entry_price = order_price / 100
        desired_contracts = int(position_capital / entry_price)

        # Cap by available cash
        max_affordable_contracts = int(available_cash / entry_price)
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
            logger.info(f"BUY {contracts} {side} @ {order_price}¢ on {ticker} (cost: ${total_cost:.2f}, wanted: {desired_contracts})")

            self.held_positions[ticker] = {"side": side, "contracts": contracts}
            self.monitored_markets.pop(ticker, None)
            self.buy_attempts.pop(ticker, None)
        except Exception as e:
            logger.error(f"Buy order failed for {ticker}: {e}")

    def _close_position(self, ticker: str, position: dict):
        """Close position at best available price."""
        try:
            # Get current market data to determine exit price
            markets = self.trader.get_markets(tickers=[ticker])
            if not markets:
                exit_price = 1  # Default emergency exit
            else:
                market = markets[0]
                side = position["side"]
                bid = int(float(getattr(market, f"{side}_bid_dollars", "0")) * 100)
                ask = int(float(getattr(market, f"{side}_ask_dollars", "0")) * 100)
                spread = ask - bid

                # If spread is reasonable, try to get bid price; otherwise emergency exit
                exit_price = max(bid, 1) if spread < 50 else 1

            self.trader.close_position(
                ticker=ticker,
                side=position["side"],
                quantity=position["contracts"],
                price=exit_price,
                order_type="limit"
            )
            logger.info(f"CLOSED {position['contracts']} {position['side']} on {ticker} @ {exit_price}¢")

            self.held_positions.pop(ticker, None)
            self.stop_loss_attempts.pop(ticker, None)
        except Exception as e:
            logger.error(f"Position close failed for {ticker}: {e}")