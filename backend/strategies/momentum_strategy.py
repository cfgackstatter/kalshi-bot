import numpy as np
import logging
from collections import deque
from datetime import datetime, timezone
from market_utils import MarketPrices, market_time_info, is_illiquid
from strategies.base_strategy import BaseStrategy, kelly_contracts
from market_utils import kalshi_fee, is_profitable

logger = logging.getLogger(__name__)
trade_logger = logging.getLogger("trades")


# ── Module-level helpers ──────────────────────────────────────────────────────

def momentum_signal(history: deque) -> tuple[float, float]:
    """
    Returns (slope_cents_per_min, tstat) for the given price history.
    Slope is in cents per minute, t-stat is the usual regression t-stat.
    """
    times = np.array([(ts - history[0][0]).total_seconds() for ts, _ in history])
    mids  = np.array([mid for _, mid in history])

    if len(times) < 3:  # need at least 3 points
        return 0.0, 0.0

    time_var = ((times - times.mean()) ** 2).sum()
    if time_var == 0:
        return 0.0, 0.0

    x = np.vstack([times, np.ones(len(times))]).T
    slope_per_sec, intercept = np.linalg.lstsq(x, mids, rcond=None)[0]
    residuals = mids - (slope_per_sec * times + intercept)

    rss = (residuals ** 2).sum()
    if rss == 0:
        return 0.0, 0.0

    se = np.sqrt(rss / (len(times) - 2)) / np.sqrt(time_var)
    if se == 0:
        return 0.0, 0.0

    tstat = float(slope_per_sec / se)
    slope_cents_per_min = float(slope_per_sec * 60.0)  # convert to ¢/min

    return slope_cents_per_min, tstat


# ── Strategy class ────────────────────────────────────────────────────────────

class MomentumStrategy(BaseStrategy):
    """
    Buys markets showing statistically significant price trends using linear regression.
    A t-statistic is computed over the rolling `momentum_window_minutes` window —
    capturing both trend direction and consistency of fit, not just first-to-last price delta.

    Entry:  t-stat exceeds `momentum_tstat_threshold` (positive → buy YES, negative → buy NO),
            subject to minimum upside filters (`min_upside_cents`, `min_upside_ratio`)
    Exit:   take-profit at `take_profit_cents` gain, stop-loss at `stop_loss_cents` loss,
            or time-based exit when `max_hold_minutes` exceeded
    """

    def __init__(self, trader, config: dict):
        super().__init__(trader, config)
        # ticker → deque of (timestamp, mid_price) tuples
        self.price_history: dict[str, deque] = {}

    # ── Scan ──────────────────────────────────────────────────────────────────

    def scan_markets(self) -> list[str]:
        """Fetch all open markets within the configured time window and build watchlist."""

        now = datetime.now(timezone.utc)
        min_secs = self.config.get("min_time_to_expiry", 1.0) * 3600
        max_secs = self.config.get("max_time_to_expiry", 6.0) * 3600
        min_volume = self.config.get("min_volume", 10)
        excludes = [s.strip() for s in
                    self.config.get("ticker_exclude_substrings", "").split(",") if s.strip()]

        try:
            max_ts = int(now.timestamp() + max_secs)
            all_mkts = self.trader.get_markets(status="open", max_close_ts=max_ts)
        except Exception as e:
            logger.error(f"[Momentum] Market fetch failed: {e}")
            return list(self.monitored_markets.keys())

        eligible = []
        fresh_markets = {}

        for m in all_mkts:
            ticker = m.ticker

            # Skip already held
            if ticker in self.held_positions:
                continue

            # Exclude substrings
            if any(ex in ticker for ex in excludes):
                continue

            prices = MarketPrices.from_market(m)
            if is_illiquid(prices):
                continue

            secs_left = market_time_info(m, now)["total_seconds_left"]
            if not (min_secs <= secs_left <= max_secs):
                continue

            volume = getattr(m, "volume", 0) or 0
            if volume < min_volume:
                continue

            fresh_markets[ticker] = {
                "yes_bid": prices.yes_bid,
                "yes_ask": prices.yes_ask,
                "no_bid":  prices.no_bid,
                "no_ask":  prices.no_ask,
                "secs_left": secs_left,
            }
            eligible.append(ticker)

        # Remove tickers no longer eligible, keep price_history for ones still in
        stale = set(self.monitored_markets) - set(fresh_markets)
        for ticker in stale:
            self.monitored_markets.pop(ticker, None)
            self.price_history.pop(ticker, None)  # reset history for dropped tickers

        self.monitored_markets.update(fresh_markets)

        logger.info(f"[Momentum] {len(eligible)} eligible markets in watchlist")
        return eligible

    # ── WebSocket price callback ───────────────────────────────────────────────

    def _check_buying_opportunity(self, ticker: str, prices: MarketPrices):
        if not self.config.get("enabled", False):
            return

        now = datetime.now(timezone.utc)
        window_secs = self.config.get("momentum_window_minutes", 5) * 60

        if ticker not in self.price_history:
            self.price_history[ticker] = deque()

        history = self.price_history[ticker]
        mid = (prices.yes_bid + prices.yes_ask) / 2
        history.append((now, mid))
        # logger.debug(f"[Momentum] tick {ticker} mid={mid:.1f}¢ history={len(history)}")

        cutoff = now.timestamp() - window_secs
        while history and history[0][0].timestamp() < cutoff:
            history.popleft()

        if len(history) < 5:
            return
        oldest_ts = history[0][0]
        if (now.timestamp() - oldest_ts.timestamp()) < window_secs * 0.8:
            return

        slope_cpm, tstat = momentum_signal(history)
        t_threshold = self.config.get("momentum_tstat_threshold", 2.5)
        min_slope   = self.config.get("min_slope_cents_per_min", 0.0)

        if abs(tstat) < t_threshold:
            return
        if abs(slope_cpm) < min_slope:
            return

        side = "yes" if tstat > 0 else "no"

        _, ask = prices.for_side(side)
        upside = 100 - ask

        min_upside = self.config.get("min_upside_cents", 5)
        if upside < min_upside:
            # logger.debug(f"[Momentum] SKIP {ticker} {side}: only {upside}¢ upside remaining")
            return

        if ask <= 0:
            # logger.debug(f"[Momentum] SKIP {ticker} {side}: ask is 0")
            return

        min_ratio = self.config.get("min_upside_ratio", 0.1)
        if upside / ask < min_ratio:
            # logger.debug(f"[Momentum] SKIP {ticker} {side}: upside/downside={upside/ask:.2f} < {min_ratio}")
            return

        logger.info(
            f"[Momentum] {ticker} {side.upper()} signal: "
            f"slope={slope_cpm:+.2f}¢/min "
            f"t-stat={tstat:+.2f} over last "
            f"{(now.timestamp() - oldest_ts.timestamp()) / 60:.1f}min "
            f"({len(history)} ticks) | upside={upside}¢ ratio={upside/ask:.2f}"
        )
        self._execute_buy(ticker, side, prices)

    # ── Entry execution (reuses base kelly + fee logic) ───────────────────────

    def _execute_buy(self, ticker: str, side: str, prices: MarketPrices):       
        now          = datetime.now(timezone.utc)
        last_attempt = self.buy_attempts.get(ticker)
        if last_attempt and (now - last_attempt).total_seconds() < 10:
            return

        bid, ask = prices.for_side(side)
        maker = self.config.get("order_at_bid", False)
        order_price = min(bid, 99) if maker else min(ask, 99)

        if order_price <= 0:
            # logger.debug(f"[Momentum] SKIP {ticker}: order_price is 0")
            return

        min_price = self.config.get("min_contract_price_cents", 1)
        if order_price < min_price:
            # logger.info(f"[Momentum] SKIP {ticker} {side}: order_price={order_price}¢ < min={min_price}¢")
            return

        max_spread = self.config.get("max_spread", 3)
        spread = ask - bid
        if spread > max_spread:
            # logger.info(f"[Momentum] SKIP {ticker} {side}: spread={spread}¢ > max={max_spread}¢")
            return

        try:
            balance         = self.trader.get_balance()
            total_portfolio = balance["balance"] + balance["portfolio_value"]
            available_cash  = balance["balance"]
        except Exception as e:
            logger.error(f"[Momentum] Balance fetch failed: {e}")
            return

        contracts = kelly_contracts(
            order_price    = order_price,
            edge           = self.config.get("estimated_edge", 0.03),
            portfolio      = total_portfolio,
            kelly_fraction = self.config.get("kelly_fraction", 0.25),
            max_pct        = self.config.get("max_position_pct", 0.05),
            available_cash = available_cash,
        )
        if contracts < 1:
            return

        # Profitability gate: worst-case taker fee
        if not is_profitable(contracts, order_price, maker=False):
            logger.debug(f"[Momentum] SKIP {ticker}: not profitable after fees")
            return

        logger.info(
            f"[Momentum] _execute_buy {ticker} {side}: order_price={order_price}¢ "
            f"spread={spread}¢ contracts={contracts} "
            f"min_price={min_price}¢"
        )

        self.buy_attempts[ticker] = now
        try:
            self.trader.create_order(
                ticker=ticker, side=side, quantity=contracts, price=order_price
            )
            self.held_positions[ticker] = {
                "side":         side,
                "contracts":    contracts,
                "entry_price":  order_price,
                "entry_time":   now.isoformat(),
            }
            self.monitored_markets.pop(ticker, None)
            self.price_history.pop(ticker, None)
            self.buy_attempts.pop(ticker, None)
            fee = kalshi_fee(contracts, order_price, maker=maker)
            trade_logger.info(
                f"[Momentum] BUY {contracts} {side.upper()} @ {order_price}¢ on {ticker} "
                f"(cost=${contracts * order_price / 100:.2f}, fee=${fee:.4f})"
            )
        except Exception as e:
            self.buy_attempts.pop(ticker, None)
            logger.error(f"[Momentum] Buy failed for {ticker}: {e}")

    # ── Exit logic ────────────────────────────────────────────────────────────

    def _check_exit_conditions(self, ticker: str, prices: MarketPrices):
        """
        Called on every WebSocket tick for held positions.
        Exits on:
        - hard take-profit at 99¢ bid
        - normal take-profit
        - stop-loss
        - max hold time
        """

        # Do nothing if strategy is disabled (e.g. after /stop)
        if not self.config.get("enabled", False):
            return

        # Keep a rolling mid-price history for held positions too
        now = datetime.now(timezone.utc)
        window_secs = self.config.get("momentum_window_minutes", 5) * 60

        if ticker not in self.price_history:
            self.price_history[ticker] = deque()

        history = self.price_history[ticker]
        mid = (prices.yes_bid + prices.yes_ask) / 2
        history.append((now, mid))

        cutoff = now.timestamp() - window_secs
        while history and history[0][0].timestamp() < cutoff:
            history.pop()

        if is_illiquid(prices):
            return

        pos = self.held_positions.get(ticker)
        if not pos:
            return

        side = pos.get("side")
        entry_price = pos.get("entry_price")
        entry_time_raw = pos.get("entry_time")

        if entry_price is None:
            # You can either silently skip or log once; this keeps it quiet:
            return

        # Normalize entry_time
        if isinstance(entry_time_raw, datetime):
            entry_time = entry_time_raw
        elif isinstance(entry_time_raw, str):
            try:
                entry_time = datetime.fromisoformat(entry_time_raw)
            except Exception:
                entry_time = datetime.now(timezone.utc)
                pos["entry_time"] = entry_time.isoformat()
        else:
            entry_time = datetime.now(timezone.utc)
            pos["entry_time"] = entry_time.isoformat()

        now = datetime.now(timezone.utc)
        current_bid, _ = prices.for_side(side)

        pnl_cents = current_bid - entry_price
        take_profit = self.config.get("take_profit_cents", 3)
        stop_loss = self.config.get("stop_loss_cents", 5)
        max_hold_minutes = self.config.get("max_hold_minutes", 30)
        hold_minutes = (now - entry_time).total_seconds() / 60

        reason = None

        # 1) Hard take-profit at 99¢
        if current_bid >= 99:
            reason = "hard take-profit at 99¢"
        # 2) Normal take-profit
        elif pnl_cents >= take_profit:
            reason = f"take-profit ({pnl_cents:+.0f}¢ >= {take_profit}¢)"
        # 3) Stop-loss
        elif pnl_cents <= -stop_loss:
            reason = f"stop-loss ({pnl_cents:+.0f}¢ <= -{stop_loss}¢)"
        # 4) Max hold time
        elif hold_minutes >= max_hold_minutes:
            reason = f"max hold time ({hold_minutes:.0f}min)"

        if reason:
            trade_logger.info(f"[Momentum] EXIT {ticker} {side.upper()} — {reason}")
            position = self.held_positions[ticker]
            self.close_position(ticker, position, prices)