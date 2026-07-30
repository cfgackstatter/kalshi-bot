from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional
import math
import logging
from kalshi_client import KalshiTrader
from market_utils import MarketPrices, position_size
from utils import parse_datetime

logger = logging.getLogger(__name__)
trade_logger = logging.getLogger("trades")


class BaseStrategy(ABC):
    """
    Abstract base for all trading strategies.
    Provides shared position tracking, order cleanup, and close logic.
    Subclasses implement: scan_markets, _check_buying_opportunity, _check_exit_conditions.
    """

    def __init__(self, trader: KalshiTrader, config: dict):
        self.trader            = trader
        self.config            = config
        self.held_positions    = {}   # ticker -> {side, contracts, entry_price, entry_time}
        self.monitored_markets = {}   # ticker -> market object / metadata
        self.buy_attempts      = {}   # ticker -> datetime (cooldown)
        self.pending_buys      = {}   # ticker -> {side, order_price, time} until fill confirmed
        self.pending_closes    = set()  # tickers with a close order in flight

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
        """Reconcile held_positions with the exchange (source of truth for fills)."""
        response = self.trader.get_positions()
        market_positions = getattr(response, "market_positions", [])

        for pos in market_positions:
            existing = self.held_positions.get(pos.ticker, {})
            pending  = self.pending_buys.pop(pos.ticker, None)
            size = position_size(pos)
            if size == 0:
                continue
            side = "yes" if size > 0 else "no"
            contracts = abs(size)
            # Order API expects whole contracts for our sizing path
            contracts_i = max(1, int(round(contracts)))

            # Prefer in-memory / pending order price; else infer from Kalshi exposure
            entry_price = existing.get("entry_price") or (pending or {}).get("order_price")
            if entry_price is None and contracts > 0:
                try:
                    cost_excl_fees = float(getattr(pos, "market_exposure_dollars", 0) or 0)
                    entry_price = round(cost_excl_fees / contracts * 100)  # dollars → cents
                    logger.info(
                        f"[Positions] Inferred entry_price for {pos.ticker} "
                        f"{side.upper()}: {entry_price}¢ from market_exposure"
                    )
                except Exception as e:
                    logger.warning(f"[Positions] Could not infer entry_price for {pos.ticker}: {e}")

            entry_time = existing.get("entry_time") or (pending or {}).get("time")
            if entry_time is None:
                entry_time = datetime.now(timezone.utc).isoformat()
                logger.info(
                    f"[Positions] No entry_time for {pos.ticker}, using now as fallback "
                    f"(max_hold_minutes will be measured from restart)"
                )

            # Preserve strategy origin (bonding | momentum) across restarts/reconciles
            origin = existing.get("origin") or (pending or {}).get("origin")

            held = {
                "side":        side,
                "contracts":   contracts_i,
                "entry_price": entry_price,
                "entry_time":  entry_time,
            }
            if origin:
                held["origin"] = origin
            self.held_positions[pos.ticker] = held
            # Filled — stop watching for entry
            self.monitored_markets.pop(pos.ticker, None)
            if hasattr(self, "price_history"):
                self.price_history.pop(pos.ticker, None)

        active = {pos.ticker for pos in market_positions if position_size(pos) != 0}
        for ticker in list(self.held_positions):
            if ticker not in active:
                del self.held_positions[ticker]
                self.pending_closes.discard(ticker)

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
                        # Clear any in-flight tracking for this ticker
                        self.pending_buys.pop(order.ticker, None)
                        self.pending_closes.discard(order.ticker)
                        logger.info(f"Cancelled stale order: {order.ticker}")
                except Exception as e:
                    logger.error(f"Failed to cancel {order.order_id}: {e}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    def close_position(self, ticker: str, position: dict,
                       prices: Optional[MarketPrices] = None, emergency: bool = False):
        """Place a close order; position is removed only once the exchange confirms flat."""
        if ticker in self.pending_closes:
            return
        try:
            # Guard: skip if market is no longer open
            markets = self.trader.get_markets(tickers=[ticker])
            if markets:
                status = getattr(markets[0], "status", "active")
                if status in ("settled", "finalized", "closed"):
                    logger.warning(f"SKIP CLOSE {ticker}: market status='{status}', removing position")
                    self.held_positions.pop(ticker, None)
                    self.pending_closes.discard(ticker)
                    return
                if status != "active":
                    logger.warning(f"[Close] {ticker} status='{status}', attempting close anyway")
            else:
                logger.warning(f"[Close] {ticker}: get_markets returned empty, attempting close anyway")

            side = position["side"]

            # Prefer REST book over WS-inferred NO prices when available
            if markets:
                rest_bid, rest_ask = MarketPrices.from_market(markets[0]).for_side(side)
            else:
                rest_bid, rest_ask = 0, 0
            if prices is not None:
                ws_bid, ws_ask = prices.for_side(side)
            else:
                ws_bid, ws_ask = rest_bid, rest_ask

            # Use REST quotes if they look live; else WS
            if rest_bid > 0 or rest_ask < 100:
                bid, ask = rest_bid, rest_ask
            else:
                bid, ask = ws_bid, ws_ask

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
            self.pending_closes.add(ticker)
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

            self.update_positions()  # clear held if the close filled immediately

        except Exception as e:
            self.pending_closes.discard(ticker)
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
    """
    Fractional-Kelly size in contracts.

    - Caps edge so implied fair prob never exceeds ~99.5%
    - Hard-caps notional at max_position_pct (floor)
    - Sole exception: if the pct budget is > 0 but < 1 contract, round up to 1
      when cash allows (never 2+)
    """
    if order_price <= 0 or available_cash <= 0 or portfolio <= 0 or max_pct <= 0:
        return 0

    implied_prob = order_price / 100
    payout_odds  = max(1 - implied_prob, 0.01)
    edge = min(max(edge, 0.0), max(0.995 - implied_prob, 0.0))
    if edge <= 0:
        return 0

    kelly      = edge / payout_odds
    safe_kelly = min(kelly * kelly_fraction, max_pct)
    capital    = portfolio * safe_kelly

    price_dollars  = order_price / 100
    max_affordable = int(available_cash / price_dollars)
    # Strict max-position cap in contracts (floor)
    max_by_pct     = int(portfolio * max_pct / price_dollars)

    if max_affordable < 1:
        return 0

    desired = math.ceil(capital / price_dollars - 1e-12) if capital > 0 else 0
    n = min(desired, max_affordable, max_by_pct)

    # Round up to exactly 1 when pct budget is positive but < one contract
    if n < 1 and max_affordable >= 1 and portfolio * max_pct > 0:
        return 1
    return max(n, 0)
