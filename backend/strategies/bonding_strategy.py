from datetime import datetime, timezone, timedelta
from strategies.base_strategy import BaseStrategy, kelly_contracts
from market_utils import (
    MarketPrices, is_illiquid, kalshi_fee, market_volume,
    is_profitable, market_time_info,
)
import logging

logger = logging.getLogger(__name__)
trade_logger = logging.getLogger("trades")


class BondingStrategy(BaseStrategy):
    """
    High-probability bonding strategy.
    Buys YES/NO near certainty, requires a stable ask, holds to settlement,
    and only exits early if the thesis clearly breaks.
    """

    def __init__(self, trader, config: dict):
        super().__init__(trader, config)
        # (ticker, side) → when ask first continuously met min_probability
        self._ask_stable_since: dict[tuple[str, str], datetime] = {}
        # ticker → earliest time we may rebuy after a prior trade / close
        self._rebuy_after: dict[str, datetime] = {}
        # Dedupe skip spam: (ticker, side, reason) → last log time
        self._skip_log_at: dict[tuple, datetime] = {}

    def _log_skip_once(self, ticker: str, side: str, reason: str, msg: str,
                       now: datetime, cooldown_s: float = 120.0):
        key = (ticker, side, reason)
        last = self._skip_log_at.get(key)
        if last and (now - last).total_seconds() < cooldown_s:
            logger.debug(msg)
            return
        self._skip_log_at[key] = now
        logger.info(msg)

    def scan_markets(self) -> list[str]:
        now          = datetime.now(timezone.utc)
        max_close_ts = int((now + timedelta(hours=self.config["max_time_to_expiry"])).timestamp())
        markets      = self.trader.get_markets(status="open", max_close_ts=max_close_ts)

        fresh = {}
        for market in markets:
            if market.ticker in self.held_positions or market.ticker in self.pending_buys:
                continue
            if self._passes_filters(market):
                fresh[market.ticker] = market

        dropped = set(self.monitored_markets) - set(fresh)
        for ticker in dropped:
            self.monitored_markets.pop(ticker, None)
            self._clear_stability(ticker)

        self.monitored_markets.update(fresh)
        eligible = list(fresh)
        logger.info(f"[Bonding] Scan: {len(eligible)} eligible markets")
        return eligible

    # ── Private ─────────────────────────────────────────────────────────────

    @staticmethod
    def _series_key(ticker: str) -> str:
        """
        Correlation bucket: KXBTC15M / KXBTCD / KXBTC → BTC.
        Weather city markets (LOWT*, HIGHT*, HIGH*, LOW*, RAIN*) → WEATHER.
        """
        head = ticker.split("-", 1)[0].upper()
        if head.startswith("KX"):
            head = head[2:]
        for suffix in ("15M", "1H", "1D"):
            if head.endswith(suffix):
                head = head[: -len(suffix)]
                break
        else:
            if len(head) > 3 and head[-1] in "DH" and head[-2].isalpha():
                head = head[:-1]
        # Highly correlated weather / temp contracts share one slot
        for prefix in ("LOWT", "HIGHT", "RAIN", "SNOW", "TEMP"):
            if head.startswith(prefix):
                return "WEATHER"
        if head.startswith("HIGH") or head.startswith("LOW"):
            return "WEATHER"
        return head or ticker.split("-", 1)[0]

    def _open_tickers(self) -> set[str]:
        return set(self.held_positions) | set(self.pending_buys)

    def _series_exposure_count(self, series: str) -> int:
        return sum(1 for t in self._open_tickers() if self._series_key(t) == series)

    def _open_position_count(self) -> int:
        return len(self._open_tickers())

    def _clear_stability(self, ticker: str):
        for key in list(self._ask_stable_since):
            if key[0] == ticker:
                del self._ask_stable_since[key]

    def _update_ask_stability(self, ticker: str, side: str, ask: int, now: datetime) -> bool:
        """Return True if ask has stayed ≥ min_probability for stability_seconds."""
        min_ask = self.config["min_probability"]
        need = self.config.get("stability_seconds", 90)
        key = (ticker, side)

        if ask < min_ask:
            self._ask_stable_since.pop(key, None)
            return False

        since = self._ask_stable_since.get(key)
        if since is None:
            self._ask_stable_since[key] = now
            return need <= 0

        return (now - since).total_seconds() >= need

    def _passes_filters(self, market) -> bool:
        excludes = self.config.get("ticker_exclude_substrings", "")
        if excludes:
            parts = [s.strip().lower() for s in excludes.split(",") if s.strip()]
            if any(p in market.ticker.lower() for p in parts):
                return False

        prices = MarketPrices.from_market(market)
        if is_illiquid(prices):
            return False

        volume = market_volume(market)
        if volume < self.config.get("min_volume", 0):
            return False

        max_spread = self.config.get("max_spread", 99)
        yes_spread = prices.yes_ask - prices.yes_bid
        no_spread  = prices.no_ask - prices.no_bid
        if yes_spread > max_spread and no_spread > max_spread:
            return False

        return True

    def _check_buying_opportunity(self, ticker: str, prices: MarketPrices):
        market = self.monitored_markets.get(ticker)
        if not market:
            return
        now = datetime.now(timezone.utc)
        for side in ["yes", "no"]:
            if self._should_buy(ticker, side, prices, market, now):
                self._execute_buy(ticker, side, prices, market)
                break

    def _should_buy(self, ticker: str, side: str, prices: MarketPrices,
                    market, now: datetime) -> bool:
        if ticker in self.held_positions or ticker in self.pending_buys:
            return False

        rebuy_after = self._rebuy_after.get(ticker)
        if rebuy_after and now < rebuy_after:
            return False

        max_open = self.config.get("max_open_positions", 0)
        if max_open > 0 and self._open_position_count() >= max_open:
            return False

        max_per_series = self.config.get("max_positions_per_series", 1)
        if max_per_series > 0:
            series = self._series_key(ticker)
            if self._series_exposure_count(series) >= max_per_series:
                return False

        bid, ask = prices.for_side(side)
        if ask <= 0 or bid <= 0:
            return False
        if (ask - bid) > self.config.get("max_spread", 99):
            return False
        # 99¢ leaves ≤1¢ gross — taker fee makes single-contract entries unprofitable
        max_ask = self.config.get("max_entry_ask", 98)
        if ask > max_ask or ask < self.config["min_probability"]:
            self._ask_stable_since.pop((ticker, side), None)
            return False
        if market_volume(market) < self.config.get("min_volume", 0):
            return False

        if not self._update_ask_stability(ticker, side, ask, now):
            return False

        return True

    def _use_maker(self, market) -> bool:
        if self.config.get("order_at_bid", False):
            return True
        min_mins = self.config.get("maker_min_minutes_to_expiry", 0)
        if min_mins <= 0:
            return False
        info = market_time_info(market, datetime.now(timezone.utc))
        return info["total_seconds_left"] / 60 >= min_mins

    def _set_rebuy_cooldown(self, ticker: str, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        cool = self.config.get("rebuy_cooldown_seconds", 300)
        self._rebuy_after[ticker] = now + timedelta(seconds=cool)

    def _execute_buy(self, ticker: str, side: str, prices: MarketPrices, market):
        now = datetime.now(timezone.utc)
        last_attempt = self.buy_attempts.get(ticker)
        attempt_cool = self.config.get("buy_attempt_cooldown_seconds", 120)
        if last_attempt and (now - last_attempt).total_seconds() < attempt_cool:
            return

        bid, ask = prices.for_side(side)
        maker = self._use_maker(market)
        order_price = min(bid, 99) if maker else min(ask, 99)
        if order_price <= 0:
            return

        balance         = self.trader.get_balance()
        total_portfolio = balance["balance"] + balance["portfolio_value"]
        available_cash  = balance["balance"]

        contracts = kelly_contracts(
            order_price    = order_price,
            edge           = self.config.get("estimated_edge", 0.01),
            portfolio      = total_portfolio,
            kelly_fraction = self.config.get("kelly_fraction", 0.25),
            max_pct        = self.config.get("max_position_pct", 0.05),
            available_cash = available_cash,
        )
        if contracts < 1:
            return
        if not is_profitable(contracts, order_price, maker=maker):
            self._log_skip_once(
                ticker, side, "unprofitable",
                f"[Bonding] SKIP {ticker} {side}: {contracts}x{order_price}¢ unprofitable "
                f"({'maker' if maker else 'taker'} fee)",
                now,
            )
            # Don't re-hit balance/fees on every tick for the same dead setup
            self.buy_attempts[ticker] = now
            return

        expected_fee = kalshi_fee(contracts, order_price, maker=maker)
        worst_fee    = kalshi_fee(contracts, order_price, maker=False)
        # Compare in integer cents to avoid float underflows (0.03-0.01 < 0.02)
        net_if_win_cents = contracts * (100 - order_price) - int(round(worst_fee * 100))
        min_net_cents = int(self.config.get("min_net_if_win_cents", 1))
        if net_if_win_cents < min_net_cents:
            self._log_skip_once(
                ticker, side, "min_net",
                f"[Bonding] SKIP {ticker} {side}: net_if_win={net_if_win_cents}¢ "
                f"< min {min_net_cents}¢ ({contracts}x{order_price}¢)",
                now,
            )
            self.buy_attempts[ticker] = now
            return

        total_cost = contracts * order_price / 100
        self.buy_attempts[ticker] = now
        try:
            self.trader.create_order(
                ticker=ticker, side=side, quantity=contracts, price=order_price
            )
            self.pending_buys[ticker] = {
                "side":        side,
                "order_price": order_price,
                "time":        now.isoformat(),
                "origin":      "bonding",
            }
            # Block immediate re-entry even if order cancels / doesn't fill
            self._set_rebuy_cooldown(ticker, now)
            self._clear_stability(ticker)
            trade_logger.info(
                f"[Bonding] BUY {contracts} {side} @ {order_price}¢ on {ticker} | "
                f"cost=${total_cost:.2f} "
                f"fee=${expected_fee:.4f}({'maker' if maker else 'taker'}) "
                f"worst_net_if_win={net_if_win_cents}¢"
            )
            self.update_positions()
        except Exception as e:
            self.buy_attempts.pop(ticker, None)
            self.pending_buys.pop(ticker, None)
            logger.error(f"[Bonding] Buy failed for {ticker}: {e}")

    def update_positions(self):
        """Track closes so we don't immediately rebuy the same ticker."""
        before = set(self.held_positions)
        super().update_positions()
        after = set(self.held_positions)
        for ticker in before - after:
            self._set_rebuy_cooldown(ticker)
            self._clear_stability(ticker)

    def _check_exit_conditions(self, ticker: str, prices: MarketPrices):
        if ticker in self.pending_closes:
            return
        if is_illiquid(prices):
            return

        position    = self.held_positions[ticker]
        side        = position["side"]
        bid, ask    = prices.for_side(side)
        mid         = (bid + ask) / 2
        entry_price = position.get("entry_price") or mid

        if not self.config.get("hold_to_settlement", True):
            min_tp = self.config.get("min_take_profit_cents", 3)
            if bid >= 99 and entry_price <= 98 and (bid - entry_price) >= min_tp:
                logger.info(f"[Bonding] TAKE-PROFIT: {ticker} {side} "
                            f"bid={bid}¢ entry={entry_price}¢ profit={bid - entry_price:+}¢")
                self.close_position(ticker, position, prices)
                return

        thesis_break = self.config.get("thesis_break_mid", 50)
        if mid < thesis_break:
            logger.warning(
                f"[Bonding] THESIS-BREAK EXIT: {ticker} {side} "
                f"entry={entry_price}¢ mid={mid:.1f}¢ (< {thesis_break}¢)"
            )
            self.close_position(ticker, position, prices, emergency=True)
