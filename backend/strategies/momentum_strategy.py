import numpy as np
import logging
from collections import deque
from datetime import datetime, timezone, timedelta
from market_utils import MarketPrices, market_time_info, is_illiquid, market_volume, is_profitable
from strategies.base_strategy import BaseStrategy, kelly_contracts
from market_utils import kalshi_fee

logger = logging.getLogger(__name__)
trade_logger = logging.getLogger("trades")


def momentum_signal(history: deque) -> tuple[float, float]:
    """
    Returns (slope_cents_per_min, tstat) for the given price history.
    """
    if len(history) < 3:
        return 0.0, 0.0

    times = np.array([(ts - history[0][0]).total_seconds() for ts, _ in history])
    mids  = np.array([mid for _, mid in history])

    time_var = ((times - times.mean()) ** 2).sum()
    if time_var == 0:
        return 0.0, 0.0

    x = np.vstack([times, np.ones(len(times))]).T
    slope_per_sec, intercept = np.linalg.lstsq(x, mids, rcond=None)[0]
    residuals = mids - (slope_per_sec * times + intercept)
    slope_cents_per_min = float(slope_per_sec * 60.0)

    rss = (residuals ** 2).sum()
    if rss == 0:
        if slope_per_sec == 0:
            return 0.0, 0.0
        return slope_cents_per_min, 1e6 if slope_per_sec > 0 else -1e6

    se = np.sqrt(rss / (len(times) - 2)) / np.sqrt(time_var)
    if se == 0:
        if slope_per_sec == 0:
            return 0.0, 0.0
        return slope_cents_per_min, 1e6 if slope_per_sec > 0 else -1e6

    return slope_cents_per_min, float(slope_per_sec / se)


def _recent_history(history: deque, window_secs: float) -> deque:
    if not history or window_secs <= 0:
        return history
    cutoff = history[-1][0].timestamp() - window_secs
    return deque((ts, mid) for ts, mid in history if ts.timestamp() >= cutoff)


class MomentumStrategy(BaseStrategy):
    """
    Trend-following via rolling regression t-stat on YES mid.
    Positive t-stat → buy YES; negative → buy NO.
    Exits on TP/SL, max hold, or momentum flip against the position.
    """

    def __init__(self, trader, config: dict):
        super().__init__(trader, config)
        self.price_history: dict[str, deque] = {}
        self._rebuy_after: dict[str, datetime] = {}
        # ticker → entry signal t-stat (for flip detection)
        self._entry_tstat: dict[str, float] = {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _series_key(ticker: str) -> str:
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
        for prefix in ("LOWT", "HIGHT", "RAIN", "SNOW", "TEMP"):
            if head.startswith(prefix):
                return "WEATHER"
        if head.startswith("HIGH") or head.startswith("LOW"):
            return "WEATHER"
        return head or ticker.split("-", 1)[0]

    def _open_tickers(self) -> set[str]:
        return set(self.held_positions) | set(self.pending_buys)

    def _open_position_count(self) -> int:
        return len(self._open_tickers())

    def _series_exposure_count(self, series: str) -> int:
        return sum(1 for t in self._open_tickers() if self._series_key(t) == series)

    def _set_rebuy_cooldown(self, ticker: str, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        cool = self.config.get("rebuy_cooldown_seconds", 300)
        self._rebuy_after[ticker] = now + timedelta(seconds=cool)

    def _record_mid(self, ticker: str, prices: MarketPrices, now: datetime) -> deque:
        window_secs = self.config.get("momentum_window_minutes", 5) * 60
        if ticker not in self.price_history:
            self.price_history[ticker] = deque()
        history = self.price_history[ticker]
        mid = (prices.yes_bid + prices.yes_ask) / 2
        history.append((now, mid))
        cutoff = now.timestamp() - window_secs
        while history and history[0][0].timestamp() < cutoff:
            history.popleft()
        return history

    def _scaled_edge(self, tstat: float) -> float:
        """Scale estimated_edge by how much |tstat| exceeds threshold (capped)."""
        base = self.config.get("estimated_edge", 0.02)
        thresh = max(self.config.get("momentum_tstat_threshold", 3.0), 1e-6)
        mult_cap = self.config.get("edge_scale_cap", 2.0)
        scale = min(abs(tstat) / thresh, mult_cap)
        return base * scale

    # ── Scan ──────────────────────────────────────────────────────────────────

    def scan_markets(self) -> list[str]:
        now = datetime.now(timezone.utc)
        min_secs = self.config.get("min_time_to_expiry", 1.0) * 3600
        max_secs = self.config.get("max_time_to_expiry", 6.0) * 3600
        min_volume = self.config.get("min_volume", 10)
        excludes = [s.strip().lower() for s in
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
            if ticker in self.held_positions or ticker in self.pending_buys:
                continue
            if any(ex in ticker.lower() for ex in excludes):
                continue

            prices = MarketPrices.from_market(m)
            if is_illiquid(prices):
                continue

            secs_left = market_time_info(m, now)["total_seconds_left"]
            if not (min_secs <= secs_left <= max_secs):
                continue

            if market_volume(m) < min_volume:
                continue

            fresh_markets[ticker] = {
                "yes_bid": prices.yes_bid,
                "yes_ask": prices.yes_ask,
                "no_bid":  prices.no_bid,
                "no_ask":  prices.no_ask,
                "secs_left": secs_left,
            }
            eligible.append(ticker)

        # Drop watchlist entries that fell out — keep history for held positions
        stale = set(self.monitored_markets) - set(fresh_markets)
        for ticker in stale:
            self.monitored_markets.pop(ticker, None)
            if ticker not in self.held_positions:
                self.price_history.pop(ticker, None)

        self.monitored_markets.update(fresh_markets)
        logger.info(f"[Momentum] {len(eligible)} eligible markets in watchlist")
        return eligible

    # ── Entry ─────────────────────────────────────────────────────────────────

    def _check_buying_opportunity(self, ticker: str, prices: MarketPrices):
        if not self.config.get("enabled", False):
            return
        if ticker in self.held_positions or ticker in self.pending_buys:
            return

        now = datetime.now(timezone.utc)
        rebuy_after = self._rebuy_after.get(ticker)
        if rebuy_after and now < rebuy_after:
            return

        max_open = self.config.get("max_open_positions", 0)
        if max_open > 0 and len(self._open_tickers()) >= max_open:
            return

        max_per_series = self.config.get("max_positions_per_series", 1)
        if max_per_series > 0:
            series = self._series_key(ticker)
            if self._series_exposure_count(series) >= max_per_series:
                return

        window_secs = self.config.get("momentum_window_minutes", 5) * 60
        history = self._record_mid(ticker, prices, now)

        if len(history) < 5:
            return
        oldest_ts = history[0][0]
        if (now.timestamp() - oldest_ts.timestamp()) < window_secs * 0.8:
            return

        slope_cpm, tstat = momentum_signal(history)
        t_threshold = self.config.get("momentum_tstat_threshold", 3.0)
        min_slope   = self.config.get("min_slope_cents_per_min", 0.5)

        if abs(tstat) < t_threshold or abs(slope_cpm) < min_slope:
            return

        # Recent acceleration: short-window slope must agree with full-window sign
        recent_secs = self.config.get("recent_window_seconds", 90)
        recent = _recent_history(history, recent_secs)
        if len(recent) >= 3:
            recent_slope, _ = momentum_signal(recent)
            if recent_slope == 0 or (recent_slope > 0) != (slope_cpm > 0):
                return

        side = "yes" if tstat > 0 else "no"
        yes_mid = (prices.yes_bid + prices.yes_ask) / 2
        bid, ask = prices.for_side(side)
        if ask <= 0:
            return

        # Late-trend filter: don't chase after mid already ran
        max_entry_mid = self.config.get("max_entry_mid", 70)
        side_mid = yes_mid if side == "yes" else (100 - yes_mid)
        if side_mid > max_entry_mid:
            return

        # Entry price band on the contract we buy
        min_px = self.config.get("min_entry_price_cents", 20)
        max_px = self.config.get("max_entry_price_cents", 70)
        if not (min_px <= ask <= max_px):
            return

        upside = 100 - ask
        if upside < self.config.get("min_upside_cents", 8):
            return
        min_ratio = self.config.get("min_upside_ratio", 0.1)
        if upside / ask < min_ratio:
            return

        logger.info(
            f"[Momentum] {ticker} {side.upper()} signal: "
            f"slope={slope_cpm:+.2f}¢/min t-stat={tstat:+.2f} "
            f"recent={recent_slope:+.2f} mid={side_mid:.0f}¢ ask={ask}¢ "
            f"upside={upside}¢"
        )
        self._execute_buy(ticker, side, prices, tstat)

    def _execute_buy(self, ticker: str, side: str, prices: MarketPrices, tstat: float = 0.0):
        now = datetime.now(timezone.utc)
        last_attempt = self.buy_attempts.get(ticker)
        attempt_cool = self.config.get("buy_attempt_cooldown_seconds", 120)
        if last_attempt and (now - last_attempt).total_seconds() < attempt_cool:
            return

        bid, ask = prices.for_side(side)
        maker = self.config.get("order_at_bid", False)
        order_price = min(bid, 99) if maker else min(ask, 99)
        if order_price <= 0:
            return

        max_spread = self.config.get("max_spread", 4)
        if ask - bid > max_spread:
            return

        try:
            balance         = self.trader.get_balance()
            total_portfolio = balance["balance"] + balance["portfolio_value"]
            available_cash  = balance["balance"]
        except Exception as e:
            logger.error(f"[Momentum] Balance fetch failed: {e}")
            return

        edge = self._scaled_edge(tstat)
        contracts = kelly_contracts(
            order_price    = order_price,
            edge           = edge,
            portfolio      = total_portfolio,
            kelly_fraction = self.config.get("kelly_fraction", 0.25),
            max_pct        = self.config.get("max_position_pct", 0.05),
            available_cash = available_cash,
        )
        if contracts < 1:
            return
        if not is_profitable(contracts, order_price, maker=False):
            return

        self.buy_attempts[ticker] = now
        try:
            self.trader.create_order(
                ticker=ticker, side=side, quantity=contracts, price=order_price
            )
            self.pending_buys[ticker] = {
                "side":        side,
                "order_price": order_price,
                "time":        now.isoformat(),
                "tstat":       tstat,
                "origin":      "momentum",
            }
            self._entry_tstat[ticker] = tstat
            self._set_rebuy_cooldown(ticker, now)
            fee = kalshi_fee(contracts, order_price, maker=maker)
            trade_logger.info(
                f"[Momentum] BUY {contracts} {side.upper()} @ {order_price}¢ on {ticker} "
                f"(cost=${contracts * order_price / 100:.2f}, fee=${fee:.4f}, "
                f"edge={edge:.3f}, t={tstat:+.2f})"
            )
            self.update_positions()
        except Exception as e:
            self.buy_attempts.pop(ticker, None)
            self.pending_buys.pop(ticker, None)
            self._entry_tstat.pop(ticker, None)
            logger.error(f"[Momentum] Buy failed for {ticker}: {e}")

    def update_positions(self):
        before = set(self.held_positions)
        super().update_positions()
        after = set(self.held_positions)
        for ticker in before - after:
            self._set_rebuy_cooldown(ticker)
            self._entry_tstat.pop(ticker, None)
        for ticker in after - before:
            if ticker not in self._entry_tstat:
                self._entry_tstat[ticker] = 0.0

    # ── Exit ──────────────────────────────────────────────────────────────────

    def _check_exit_conditions(self, ticker: str, prices: MarketPrices):
        if not self.config.get("enabled", False):
            return
        if ticker in self.pending_closes:
            return

        now = datetime.now(timezone.utc)
        history = self._record_mid(ticker, prices, now)

        if is_illiquid(prices):
            return

        pos = self.held_positions.get(ticker)
        if not pos:
            return

        side = pos.get("side")
        entry_price = pos.get("entry_price")
        if entry_price is None:
            return

        entry_time_raw = pos.get("entry_time")
        if isinstance(entry_time_raw, datetime):
            entry_time = entry_time_raw
        elif isinstance(entry_time_raw, str):
            try:
                entry_time = datetime.fromisoformat(entry_time_raw)
            except Exception:
                entry_time = now
                pos["entry_time"] = entry_time.isoformat()
        else:
            entry_time = now
            pos["entry_time"] = entry_time.isoformat()

        current_bid, _ = prices.for_side(side)
        pnl_cents = current_bid - entry_price
        take_profit = self.config.get("take_profit_cents", 15)
        stop_loss = self.config.get("stop_loss_cents", 10)
        max_hold_minutes = self.config.get("max_hold_minutes", 20)
        hold_seconds = (now - entry_time).total_seconds()
        hold_minutes = hold_seconds / 60
        min_flip_hold = self.config.get("min_hold_seconds_before_flip", 180)

        reason = None

        # Momentum flip against position — only after a minimum hold (anti-whipsaw)
        if (
            self.config.get("exit_on_flip", True)
            and hold_seconds >= min_flip_hold
            and len(history) >= 5
        ):
            _, tstat = momentum_signal(history)
            flip_thresh = self.config.get("flip_tstat_threshold", 3.5)
            if side == "yes" and tstat <= -flip_thresh:
                reason = f"momentum flip (t={tstat:+.2f})"
            elif side == "no" and tstat >= flip_thresh:
                reason = f"momentum flip (t={tstat:+.2f})"

        if reason is None:
            if pnl_cents >= take_profit:
                reason = f"take-profit ({pnl_cents:+.0f}¢ >= {take_profit}¢)"
            elif pnl_cents <= -stop_loss:
                reason = f"stop-loss ({pnl_cents:+.0f}¢ <= -{stop_loss}¢)"
            elif hold_minutes >= max_hold_minutes:
                reason = f"max hold time ({hold_minutes:.0f}min)"

        if reason:
            trade_logger.info(f"[Momentum] EXIT {ticker} {side.upper()} — {reason}")
            self.close_position(ticker, pos, prices)
            self._entry_tstat.pop(ticker, None)
            self._set_rebuy_cooldown(ticker, now)
