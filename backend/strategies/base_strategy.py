from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional
from kalshi_client import KalshiTrader
from market_utils import MarketPrices
from utils import parse_datetime
import logging

logger = logging.getLogger(__name__)
trade_logger = logging.getLogger("trades")


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
        # Ignore all ticks when strategy is disabled
        if not self.config.get("enabled", False):
            return

        ticker = ticker_data.get("market_ticker")
        if not ticker:
            return

        prices = MarketPrices.from_ticker_data(ticker_data)
        if ticker in self.held_positions:
            self._check_exit_conditions(ticker, prices)
        elif ticker in self.monitored_markets:
            self._check_buying_opportunity(ticker, prices)

    def update_positions(self):
        response = self.trader.get_positions()
        market_positions = getattr(response, "market_positions", [])

        for pos in market_positions:
            existing = self.held_positions.get(pos.ticker, {})
            side = "yes" if pos.position > 0 else "no"
            contracts = abs(pos.position)

            # Preserve entry_price from memory; infer from Kalshi if missing
            entry_price = existing.get("entry_price")
            if entry_price is None and contracts > 0:
                try:
                    cost_excl_fees = float(pos.market_exposure_dollars)
                    entry_price = round(cost_excl_fees / contracts * 100)  # dollars → cents
                    logger.info(
                        f"[Positions] Inferred entry_price for {pos.ticker} "
                        f"{side.upper()}: {entry_price}¢ from market_exposure"
                    )
                except Exception as e:
                    logger.warning(f"[Positions] Could not infer entry_price for {pos.ticker}: {e}")

            # Preserve entry_time from memory; use now as fallback
            entry_time = existing.get("entry_time")
            if entry_time is None:
                entry_time = datetime.now(timezone.utc).isoformat()
                logger.info(
                    f"[Positions] No entry_time for {pos.ticker}, using now as fallback "
                    f"(max_hold_minutes will be measured from restart)"
                )

            self.held_positions[pos.ticker] = {
                "side":        side,
                "contracts":   contracts,
                "entry_price": entry_price,
                "entry_time":  entry_time,
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
            # Guard: skip if market is no longer open
            markets = self.trader.get_markets(tickers=[ticker])
            if markets:
                status = getattr(markets[0], "status", "active")
                if status in ("settled", "finalized", "closed"):
                    logger.warning(f"SKIP CLOSE {ticker}: market status='{status}', removing position")
                    self.held_positions.pop(ticker, None)
                    return
                if status != "active":
                    logger.warning(f"[Close] {ticker} status='{status}', attempting close anyway")
            else:
                logger.warning(f"[Close] {ticker}: get_markets returned empty, attempting close anyway")
            
            side = position["side"]

            if prices is None:
                bid, ask = MarketPrices.from_market(markets[0]).for_side(side)
            else:
                bid, ask = prices.for_side(side)

            spread = ask - bid

            if emergency or spread >= 50:
                order_type, exit_price = "market", None
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
            logger.info(
                f"[Exit] Placed {order_type} close for {ticker} {side.upper()} "
                f"@ {exit_price}¢ x{position['contracts']}"
            )

            entry = position.get("entry_price")
            if entry and exit_price:
                pnl     = (exit_price - entry) * position["contracts"] / 100
                pnl_pct = (exit_price - entry) / entry * 100
                trade_logger.info(f"CLOSED {position['contracts']} {side} {ticker} @ {exit_price}¢ "
                                  f"(entry={entry}¢ P&L=${pnl:.2f} {pnl_pct:+.1f}%)")
            else:
                label = "MARKET" if order_type == "market" else f"{exit_price}¢"
                trade_logger.info(f"CLOSED {position['contracts']} {side} {ticker} @ {label}")

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


def kelly_contracts(order_price: int, edge: float, portfolio: float,
                    kelly_fraction: float, max_pct: float, available_cash: float) -> int:
    implied_prob = order_price / 100
    odds         = max(1 - implied_prob, 0.01)
    kelly        = edge / odds
    safe_kelly   = min(kelly * kelly_fraction, max_pct)
    capital      = portfolio * max(safe_kelly, 0.005)

    price_dollars  = order_price / 100
    desired        = int(capital / price_dollars)
    max_affordable = int(available_cash / price_dollars)

    if max_affordable < 1:
        return 0                          # can't afford even 1 contract — hard stop

    return max(min(desired, max_affordable), 1)   # at least 1, but only if affordable