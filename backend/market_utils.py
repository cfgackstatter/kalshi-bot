from dataclasses import dataclass
from datetime import datetime, timezone
import math
from utils import parse_datetime


@dataclass
class MarketPrices:
    yes_bid: int
    yes_ask: int
    no_bid: int
    no_ask: int

    @classmethod
    def from_market(cls, market):
        return cls(
            yes_bid=int(float(getattr(market, "yes_bid_dollars", "0")) * 100),
            yes_ask=int(float(getattr(market, "yes_ask_dollars", "0")) * 100),
            no_bid =int(float(getattr(market, "no_bid_dollars",  "0")) * 100),
            no_ask =int(float(getattr(market, "no_ask_dollars",  "0")) * 100),
        )

    @classmethod
    def from_ticker_data(cls, data: dict):
        """
        Build MarketPrices from a Kalshi ticker message.

        The WS ticker only includes yes_bid_dollars / yes_ask_dollars.
        We infer the NO side as:
        no_bid  ≈ max(0, 1 - yes_ask)
        no_ask  ≈ max(0, 1 - yes_bid)
        """
        yes_bid_d = float(data.get("yes_bid_dollars", "0"))
        yes_ask_d = float(data.get("yes_ask_dollars", "0"))

        # Infer NO side from YES side (binary market)
        no_bid_d = max(0.0, 1.0 - yes_ask_d)
        no_ask_d = max(0.0, 1.0 - yes_bid_d)

        return cls(
            yes_bid=int(yes_bid_d * 100),
            yes_ask=int(yes_ask_d * 100),
            no_bid =int(no_bid_d  * 100),
            no_ask =int(no_ask_d  * 100),
        )

    def for_side(self, side: str) -> tuple[int, int]:
        """Returns (bid, ask) for the given side."""
        return (self.yes_bid, self.yes_ask) if side == "yes" else (self.no_bid, self.no_ask)


def market_time_info(market, now: datetime) -> dict:
    """Extract timing and price fields from a market object."""
    close_time = parse_datetime(market.close_time)
    time_left  = close_time - now
    prices     = MarketPrices.from_market(market)
    return {
        "close_time":         close_time,
        "days_left":          max(time_left.days, 0),
        "hours_left":         time_left.seconds // 3600,
        "minutes_left":       (time_left.seconds % 3600) // 60,
        "total_seconds_left": max(time_left.total_seconds(), 0),
        "settlement_seconds": getattr(market, "settlement_timer_seconds", 0),
        **prices.__dict__,
    }


def format_position(pos, market_info: dict) -> dict:
    side      = "yes" if pos.position > 0 else "no"
    contracts = abs(pos.position)

    cost_excl_fees  = float(pos.market_exposure_dollars)
    fees            = float(pos.fees_paid_dollars)
    cash_paid       = cost_excl_fees + fees

    # avg_price in dollars, full precision (e.g. 0.985 for two contracts with 1¢ fee)
    avg_price_dollars = (cost_excl_fees / contracts) if contracts else 0

    bid = market_info["yes_bid"] if side == "yes" else market_info["no_bid"]

    return {
        "ticker":             pos.ticker,
        "side":               side,
        "contracts":          contracts,
        "avg_price":          avg_price_dollars,      # e.g. 0.985 (dollars, full precision)
        "cost":               cash_paid,              # e.g. $1.98 (dollars, full precision)
        "current_bid":        bid,                    # still in cents (integer) for consistency
        "payout_if_right":    float(contracts),
        "market_value":       contracts * bid / 100,
        "unrealized_return":  contracts * bid / 100 - cash_paid,
        "days_left":          market_info["days_left"],
        "hours_left":         market_info["hours_left"],
        "minutes_left":       market_info["minutes_left"],
        "total_seconds_left": market_info["total_seconds_left"],
        "yes_bid":            market_info["yes_bid"],
        "yes_ask":            market_info["yes_ask"],
        "no_bid":             market_info["no_bid"],
        "no_ask":             market_info["no_ask"],
    }


def is_illiquid(prices: MarketPrices) -> bool:
    return (prices.yes_bid == 0 and prices.yes_ask == 100) or \
           (prices.no_bid  == 0 and prices.no_ask  == 100)


def kalshi_fee(contracts: int, order_price_cents: int, maker: bool = False) -> float:
    """
    Kalshi fee: ceil(rate * C * P * (1-P)) rounded up to next cent.
    Taker rate: 7% | Maker rate: 1.75%
    """
    rate = 0.0175 if maker else 0.07
    P    = order_price_cents / 100
    return math.ceil(rate * contracts * P * (1 - P) * 100) / 100


def is_profitable(contracts: int, order_price_cents: int, maker: bool = False) -> bool:
    """Returns True if gross profit strictly exceeds Kalshi fee."""
    gross = contracts * (100 - order_price_cents) / 100
    fee   = kalshi_fee(contracts, order_price_cents, maker)
    return gross > fee
