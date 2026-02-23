from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional
from kalshi_client import KalshiTrader
from market_utils import MarketPrices
from utils import parse_datetime
import logging

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    Abstract base for all trading strategies.
    Provides shared position tracking, order cleanup, and close logic.
    Subclasses implement: scan_markets, _check_buying_opportunity, _check_exit_conditions.
    """

    def __init__(self, trader: KalshiTrader, config: dict):
        self.trader          = trader
        self.config          = config
        self.held_positions  = {}   # ticker -> {side, contracts, entry_price, entry_time}
        self.monitored_markets = {} # ticker -> market object
        self.buy_attempts    = {}   # ticker -> datetime (cooldown)

    # ── Public interface (called by main.py) ────────────────────────────────

    @abstractmethod
    def scan_markets(self) -> list[str]:
        """Scan for eligible markets; populate monitored_markets. Return tickers."""

    def update_ticker_price(self, ticker_data: dict):
        """WebSocket callback — route to exit check or buy check."""
        ticker = ticker_data.get("market_ticker")
        if not ticker:
            return
        prices = MarketPrices.from_ticker_data(ticker_data)
        if ticker in self.held_positions:
            self._check_exit_conditions(ticker, prices)
        elif ticker in self.monitored_markets:
            self._check_buying_opportunity(ticker, prices)

    def update_positions(self):
        """Sync held_positions with Kalshi API, preserving entry metadata."""
        response         = self.trader.get_positions()
        market_positions = getattr(response, "market_positions", [])

        for pos in market_positions:
            existing = self.held_positions.get(pos.ticker, {})
            self.held_positions[pos.ticker] = {
                "side":        "yes" if pos.position > 0 else "no",
                "contracts":   abs(pos.position),
                "entry_price": existing.get("entry_price"),
                "entry_time":  existing.get("entry_time"),
            }

        active = {pos.ticker for pos in market_positions}
        for ticker in list(self.held_positions):
            if ticker not in active:
                del self.held_positions[ticker]

    def cleanup_pending_orders(self):
        """Cancel resting orders older than max_pending_age_minutes."""
        max_age = self.config.get("max_pending_age_minutes", 5)
        try:
            now = datetime.now(timezone.utc)
            for order in (self.trader.get_orders(status="resting") or []):
                try:
                    age = (now - parse_datetime(order.created_time)).total_seconds() / 60
                    if age > max_age:
                        self.trader.cancel_order(order.order_id)
                        logger.info(f"Cancelled stale order: {order.ticker}")
                except Exception as e:
                    logger.error(f"Failed to cancel {order.order_id}: {e}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    def close_position(self, ticker: str, position: dict,
                       prices: Optional[MarketPrices] = None, emergency: bool = False):
        """Close a position at the best available price."""
        try:
            side = position["side"]

            if prices is None:
                markets = self.trader.get_markets(tickers=[ticker])
                if not markets:
                    logger.error(f"No market data for {ticker}, using emergency exit")
                    emergency = True
                    bid, ask = 0, 0
                else:
                    bid, ask = MarketPrices.from_market(markets[0]).for_side(side)
            else:
                bid, ask = prices.for_side(side)

            spread = ask - bid

            if emergency or spread >= 50:
                order_type, exit_price = "market", None
                logger.warning(f"MARKET ORDER: {ticker} spread={spread}¢ emergency={emergency}")
            elif bid >= 1:
                order_type, exit_price = "limit", bid
            else:
                order_type, exit_price = "limit", 1
                logger.warning(f"Bid collapsed for {ticker}, trying 1¢ exit")

            self.trader.close_position(
                ticker=ticker, side=side,
                quantity=position["contracts"],
                price=exit_price, order_type=order_type,
            )

            entry = position.get("entry_price")
            if entry and exit_price:
                pnl     = (exit_price - entry) * position["contracts"] / 100
                pnl_pct = (exit_price - entry) / entry * 100
                logger.info(f"CLOSED {position['contracts']} {side} {ticker} @ {exit_price}¢ "
                            f"(entry={entry}¢ P&L=${pnl:.2f} {pnl_pct:+.1f}%)")
            else:
                label = "MARKET" if order_type == "market" else f"{exit_price}¢"
                logger.info(f"CLOSED {position['contracts']} {side} {ticker} @ {label}")

            self.held_positions.pop(ticker, None)

        except Exception as e:
            logger.error(f"Close failed for {ticker}: {e}")

    # ── Subclass hooks ───────────────────────────────────────────────────────

    @abstractmethod
    def _check_buying_opportunity(self, ticker: str, prices: MarketPrices):
        """Called when a monitored ticker gets a price update."""

    @abstractmethod
    def _check_exit_conditions(self, ticker: str, prices: MarketPrices):
        """Called when a held position gets a price update."""
