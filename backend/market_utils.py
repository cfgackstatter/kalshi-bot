from dataclasses import dataclass
from datetime import datetime, timezone
import math
from utils import parse_datetime


def _fp_number(value, default: float = 0.0) -> float:
    """Parse Kalshi fixed-point strings (e.g. '67201.08') or legacy ints."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def market_volume(market) -> int:
    """Total contracts traded — prefers volume_fp (current API), falls back to volume."""
    raw = getattr(market, "volume_fp", None)
    if raw is None:
        raw = getattr(market, "volume", 0)
    return int(_fp_number(raw))


def market_open_interest(market) -> int:
    raw = getattr(market, "open_interest_fp", None)
    if raw is None:
        raw = getattr(market, "open_interest", 0)
    return int(_fp_number(raw))


def position_size(pos) -> float:
    """
    Net contracts for a market position.
    Prefer position_fp (current API); positive = YES, negative = NO.
    """
    raw = getattr(pos, "position_fp", None)
    if raw is None:
        raw = getattr(pos, "position", 0)
    return _fp_number(raw)


@dataclass
class MarketPrices:
    yes_bid: int
    yes_ask: int
    no_bid: int
    no_ask: int

    @classmethod
    def from_market(cls, market):
        return cls(
            yes_bid=int(float(getattr(market, "yes_bid_dollars", "0") or 0) * 100),
            yes_ask=int(float(getattr(market, "yes_ask_dollars", "0") or 0) * 100),
            no_bid =int(float(getattr(market, "no_bid_dollars",  "0") or 0) * 100),
            no_ask =int(float(getattr(market, "no_ask_dollars",  "0") or 0) * 100),
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
        yes_bid_d = float(data.get("yes_bid_dollars", "0") or 0)
        yes_ask_d = float(data.get("yes_ask_dollars", "0") or 0)

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
    size      = position_size(pos)
    side      = "yes" if size > 0 else "no"
    contracts = abs(size)

    cost_excl_fees  = _fp_number(getattr(pos, "market_exposure_dollars", 0))
    fees            = _fp_number(getattr(pos, "fees_paid_dollars", 0))
    cash_paid       = cost_excl_fees + fees

    # avg_price in dollars, full precision (e.g. 0.985 for two contracts with 1¢ fee)
    avg_price_dollars = (cost_excl_fees / contracts) if contracts else 0

    bid = market_info.get("yes_bid", 0) if side == "yes" else market_info.get("no_bid", 0)

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
        "days_left":          market_info.get("days_left", 0),
        "hours_left":         market_info.get("hours_left", 0),
        "minutes_left":       market_info.get("minutes_left", 0),
        "total_seconds_left": market_info.get("total_seconds_left", 0),
        "yes_bid":            market_info.get("yes_bid", 0),
        "yes_ask":            market_info.get("yes_ask", 0),
        "no_bid":             market_info.get("no_bid", 0),
        "no_ask":             market_info.get("no_ask", 0),
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
