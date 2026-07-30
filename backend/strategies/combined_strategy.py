"""
Combined strategy: run bonding + momentum under one capital budget.

Exits are always origin-specific (never treat the two books the same).
Entries compete via prefer_mode:
  - score:          take the better time-normalized alpha (¢/hr)
  - momentum_first: bonding only fills when no momentum signal is ready
  - bonding_first:  momentum only fills when no bonding signal is ready
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from market_utils import MarketPrices, kalshi_fee, market_time_info
from strategies.base_strategy import BaseStrategy
from strategies.bonding_strategy import BondingStrategy
from strategies.momentum_strategy import MomentumStrategy, momentum_signal, _recent_history

logger = logging.getLogger(__name__)

_SHARED_KEYS = (
    "enabled",
    "max_open_positions",
    "max_positions_per_series",
    "kelly_fraction",
    "max_position_pct",
    "rebuy_cooldown_seconds",
    "buy_attempt_cooldown_seconds",
    "order_at_bid",
    "ticker_exclude_substrings",
    "max_pending_age_minutes",
)


class CombinedStrategy(BaseStrategy):
    def __init__(self, trader, config: dict):
        super().__init__(trader, config)
        self._rebuy_after: dict[str, datetime] = {}

        self.bonding = BondingStrategy(trader, self._leg_config("bonding"))
        self.momentum = MomentumStrategy(trader, self._leg_config("momentum"))
        self._wire_shared_state()

    # ── Shared state / config ─────────────────────────────────────────────────

    def _wire_shared_state(self):
        """Both legs trade against one position book and one rebuy map."""
        for leg in (self.bonding, self.momentum):
            leg.held_positions = self.held_positions
            leg.pending_buys = self.pending_buys
            leg.pending_closes = self.pending_closes
            leg.buy_attempts = self.buy_attempts
            leg._rebuy_after = self._rebuy_after

    def _leg_config(self, origin: str) -> dict:
        nested = dict(self.config.get(origin) or {})
        for key in _SHARED_KEYS:
            if key in self.config:
                nested[key] = self.config[key]
        nested["enabled"] = self.config.get("enabled", False)
        nested["strategy_type"] = origin
        return nested

    def _sync_leg_configs(self):
        self.bonding.config = self._leg_config("bonding")
        self.momentum.config = self._leg_config("momentum")
        self._wire_shared_state()

    # ── Scoring (expected ¢ per hour of capital lock) ─────────────────────────

    @staticmethod
    def _bonding_score(ask: int, secs_left: float) -> float:
        fee_cents = kalshi_fee(1, ask, maker=False) * 100
        net = max((100 - ask) - fee_cents, 0.01)
        hours = max(secs_left / 3600.0, 1.0 / 60.0)
        return net / hours

    def _momentum_score(self, tstat: float, ask: int, secs_left: float) -> float:
        cfg = self.momentum.config
        # _scaled_edge already scales by |t|/threshold — don't multiply confidence again
        edge = self.momentum._scaled_edge(tstat)  # probability points
        expected_cents = max(edge * 100.0, 0.01)
        hold_h = cfg.get("max_hold_minutes", 15) / 60.0
        hours = max(min(hold_h, secs_left / 3600.0), 1.0 / 60.0)
        return expected_cents / hours

    def _best_bonding_score(self, now: datetime) -> float:
        best = 0.0
        for ticker, market in self.bonding.monitored_markets.items():
            if ticker in self.held_positions or ticker in self.pending_buys:
                continue
            try:
                prices = MarketPrices.from_market(market)
                secs = market_time_info(market, now)["total_seconds_left"]
            except Exception:
                continue
            for side in ("yes", "no"):
                # Soft check without mutating stability clock: ask in band + filters
                if not self._bonding_soft_ready(ticker, side, prices, market, now):
                    continue
                _, ask = prices.for_side(side)
                best = max(best, self._bonding_score(ask, secs))
        return best

    def _bonding_soft_ready(self, ticker, side, prices, market, now) -> bool:
        """Like BondingStrategy._should_buy but does not advance stability state."""
        if ticker in self.held_positions or ticker in self.pending_buys:
            return False
        rebuy_after = self._rebuy_after.get(ticker)
        if rebuy_after and now < rebuy_after:
            return False
        max_open = self.config.get("max_open_positions", 0)
        if max_open > 0 and self.bonding._open_position_count() >= max_open:
            return False
        max_per = self.config.get("max_positions_per_series", 1)
        if max_per > 0:
            series = self.bonding._series_key(ticker)
            if self.bonding._series_exposure_count(series) >= max_per:
                return False
        bid, ask = prices.for_side(side)
        if ask <= 0 or bid <= 0:
            return False
        cfg = self.bonding.config
        if (ask - bid) > cfg.get("max_spread", 99):
            return False
        if ask > 99 or ask < cfg["min_probability"]:
            return False
        key = (ticker, side)
        since = self.bonding._ask_stable_since.get(key)
        need = cfg.get("stability_seconds", 90)
        if since is None:
            return need <= 0
        return (now - since).total_seconds() >= need

    def _best_momentum_score(self, now: datetime) -> float:
        best = 0.0
        cfg = self.momentum.config
        t_threshold = cfg.get("momentum_tstat_threshold", 3.0)
        min_slope = cfg.get("min_slope_cents_per_min", 0.5)
        window_secs = cfg.get("momentum_window_minutes", 5) * 60
        recent_secs = cfg.get("recent_window_seconds", 90)

        for ticker, meta in self.momentum.monitored_markets.items():
            if ticker in self.held_positions or ticker in self.pending_buys:
                continue
            history = self.momentum.price_history.get(ticker)
            if not history or len(history) < 5:
                continue
            if (now.timestamp() - history[0][0].timestamp()) < window_secs * 0.8:
                continue
            slope_cpm, tstat = momentum_signal(history)
            if abs(tstat) < t_threshold or abs(slope_cpm) < min_slope:
                continue
            recent = _recent_history(history, recent_secs)
            if len(recent) >= 3:
                recent_slope, _ = momentum_signal(recent)
                if recent_slope == 0 or (recent_slope > 0) != (slope_cpm > 0):
                    continue
            side = "yes" if tstat > 0 else "no"
            yes_mid = (meta.get("yes_bid", 0) + meta.get("yes_ask", 100)) / 2
            ask = meta.get("yes_ask") if side == "yes" else meta.get("no_ask")
            if not ask:
                continue
            side_mid = yes_mid if side == "yes" else (100 - yes_mid)
            if side_mid > cfg.get("max_entry_mid", 70):
                continue
            if not (cfg.get("min_entry_price_cents", 20) <= ask <= cfg.get("max_entry_price_cents", 70)):
                continue
            upside = 100 - ask
            if upside < cfg.get("min_upside_cents", 8):
                continue
            if upside / ask < cfg.get("min_upside_ratio", 0.1):
                continue
            secs = meta.get("secs_left", cfg.get("max_time_to_expiry", 12) * 3600)
            best = max(best, self._momentum_score(tstat, ask, secs))
        return best

    def _rival_scores(self, now: datetime) -> dict[str, float]:
        return {
            "bonding": self._best_bonding_score(now),
            "momentum": self._best_momentum_score(now),
        }

    def _may_take(self, origin: str, score: float, rivals: dict[str, float]) -> bool:
        if score <= 0:
            return False
        mode = self.config.get("prefer_mode", "score")
        other = "momentum" if origin == "bonding" else "bonding"
        other_score = rivals.get(other, 0.0)

        if mode == f"{origin}_first":
            return True
        if mode == f"{other}_first":
            return other_score <= 0
        # score mode (default)
        hyst = float(self.config.get("score_hysteresis", 1.1))
        if other_score <= 0:
            return True
        return score >= other_score * hyst

    # ── Origin inference for orphan / restarted positions ─────────────────────

    @staticmethod
    def _infer_origin(position: dict) -> str:
        """
        Untagged inventory: high-price entries look like bonding;
        otherwise manage with momentum exits (have a stop).
        """
        entry = position.get("entry_price")
        if entry is not None and entry >= 95:
            return "bonding"
        return "momentum"

    def _origin_of(self, ticker: str) -> str:
        pos = self.held_positions.get(ticker) or {}
        return pos.get("origin") or self._infer_origin(pos)

    # ── Public interface ──────────────────────────────────────────────────────

    def scan_markets(self) -> list[str]:
        self._sync_leg_configs()
        b = self.bonding.scan_markets()
        m = self.momentum.scan_markets()
        # Union for WS subscription / dashboard watchlist
        self.monitored_markets = {}
        for t in b:
            self.monitored_markets[t] = {"origin": "bonding", "market": self.bonding.monitored_markets[t]}
        for t in m:
            if t not in self.monitored_markets:
                self.monitored_markets[t] = {"origin": "momentum", "meta": self.momentum.monitored_markets[t]}
            else:
                self.monitored_markets[t]["also"] = "momentum"
        eligible = list(set(b) | set(m))
        logger.info(
            f"[Combined] Scan: {len(b)} bonding + {len(m)} momentum "
            f"→ {len(eligible)} unique watchlist"
        )
        return eligible

    def update_ticker_price(self, ticker_data: dict):
        if not self.config.get("enabled", False):
            return

        ticker = ticker_data.get("market_ticker")
        if not ticker:
            return

        prices = MarketPrices.from_ticker_data(ticker_data)
        self._sync_leg_configs()

        if ticker in self.held_positions:
            origin = self._origin_of(ticker)
            # Persist inferred origin so later ticks stay consistent
            self.held_positions[ticker]["origin"] = origin
            if origin == "bonding":
                self.bonding._check_exit_conditions(ticker, prices)
            else:
                self.momentum._check_exit_conditions(ticker, prices)
            return

        now = datetime.now(timezone.utc)
        rivals = self._rival_scores(now)

        # Momentum first on the tick so its history keeps updating even if we defer buy
        if ticker in self.momentum.monitored_markets:
            self._try_momentum_entry(ticker, prices, now, rivals)
        if ticker in self.bonding.monitored_markets:
            self._try_bonding_entry(ticker, prices, now, rivals)

    def _try_momentum_entry(self, ticker: str, prices: MarketPrices,
                            now: datetime, rivals: dict[str, float]):
        # Record mid even when gated — need history for later signals
        history = self.momentum._record_mid(ticker, prices, now)
        if ticker in self.held_positions or ticker in self.pending_buys:
            return

        # Reuse momentum filters by peeking signal quality, then gate, then execute
        cfg = self.momentum.config
        window_secs = cfg.get("momentum_window_minutes", 5) * 60
        if len(history) < 5:
            return
        if (now.timestamp() - history[0][0].timestamp()) < window_secs * 0.8:
            return

        slope_cpm, tstat = momentum_signal(history)
        t_threshold = cfg.get("momentum_tstat_threshold", 3.0)
        min_slope = cfg.get("min_slope_cents_per_min", 0.5)
        if abs(tstat) < t_threshold or abs(slope_cpm) < min_slope:
            return

        recent = _recent_history(history, cfg.get("recent_window_seconds", 90))
        if len(recent) >= 3:
            recent_slope, _ = momentum_signal(recent)
            if recent_slope == 0 or (recent_slope > 0) != (slope_cpm > 0):
                return
        else:
            recent_slope = slope_cpm

        side = "yes" if tstat > 0 else "no"
        yes_mid = (prices.yes_bid + prices.yes_ask) / 2
        bid, ask = prices.for_side(side)
        if ask <= 0:
            return
        side_mid = yes_mid if side == "yes" else (100 - yes_mid)
        if side_mid > cfg.get("max_entry_mid", 70):
            return
        if not (cfg.get("min_entry_price_cents", 20) <= ask <= cfg.get("max_entry_price_cents", 70)):
            return
        upside = 100 - ask
        if upside < cfg.get("min_upside_cents", 8):
            return
        if upside / ask < cfg.get("min_upside_ratio", 0.1):
            return

        # Capacity / cooldown (same as leg)
        rebuy_after = self._rebuy_after.get(ticker)
        if rebuy_after and now < rebuy_after:
            return
        last_attempt = self.buy_attempts.get(ticker)
        attempt_cool = self.config.get("buy_attempt_cooldown_seconds", 180)
        if last_attempt and (now - last_attempt).total_seconds() < attempt_cool:
            return
        max_open = self.config.get("max_open_positions", 0)
        if max_open > 0 and self.momentum._open_position_count() >= max_open:
            return
        max_per = self.config.get("max_positions_per_series", 1)
        if max_per > 0:
            series = self.momentum._series_key(ticker)
            if self.momentum._series_exposure_count(series) >= max_per:
                return

        meta = self.momentum.monitored_markets.get(ticker) or {}
        secs = meta.get("secs_left", cfg.get("max_time_to_expiry", 12) * 3600)
        score = self._momentum_score(tstat, ask, secs)
        if not self._may_take("momentum", score, rivals):
            logger.info(
                f"[Combined] Defer momentum {ticker}: score={score:.2f} "
                f"(bonding rival={rivals.get('bonding', 0):.2f}, mode={self.config.get('prefer_mode')})"
            )
            return

        before_pending = ticker in self.pending_buys
        self.momentum._execute_buy(ticker, side, prices, tstat)
        if ticker in self.pending_buys and not before_pending:
            logger.info(
                f"[Combined] TAKE momentum {ticker} {side.upper()} score={score:.2f} "
                f"t={tstat:+.2f} ask={ask}¢"
            )

    def _try_bonding_entry(self, ticker: str, prices: MarketPrices,
                           now: datetime, rivals: dict[str, float]):
        market = self.bonding.monitored_markets.get(ticker)
        if not market:
            return
        for side in ("yes", "no"):
            if not self.bonding._should_buy(ticker, side, prices, market, now):
                continue
            _, ask = prices.for_side(side)
            secs = market_time_info(market, now)["total_seconds_left"]
            score = self._bonding_score(ask, secs)
            if not self._may_take("bonding", score, rivals):
                logger.info(
                    f"[Combined] Defer bonding {ticker}: score={score:.2f} "
                    f"(momentum rival={rivals.get('momentum', 0):.2f}, mode={self.config.get('prefer_mode')})"
                )
                return
            before_pending = ticker in self.pending_buys
            self.bonding._execute_buy(ticker, side, prices, market)
            if ticker in self.pending_buys and not before_pending:
                logger.info(
                    f"[Combined] TAKE bonding {ticker} {side.upper()} score={score:.2f} ask={ask}¢"
                )
            return

    def update_positions(self):
        before = set(self.held_positions)
        # Snapshot origins / pending metadata before reconcile
        origins = {t: p.get("origin") for t, p in self.held_positions.items() if p.get("origin")}
        pending_origins = {
            t: p.get("origin") for t, p in self.pending_buys.items() if p.get("origin")
        }
        pending_tstat = {
            t: p.get("tstat") for t, p in self.pending_buys.items() if "tstat" in p
        }

        super().update_positions()
        after = set(self.held_positions)

        for ticker in before - after:
            self.bonding._set_rebuy_cooldown(ticker)
            self.momentum._set_rebuy_cooldown(ticker)
            self.bonding._clear_stability(ticker)
            self.momentum._entry_tstat.pop(ticker, None)

        for ticker in after - before:
            pos = self.held_positions[ticker]
            origin = (
                pos.get("origin")
                or pending_origins.get(ticker)
                or origins.get(ticker)
                or self._infer_origin(pos)
            )
            pos["origin"] = origin
            if origin == "momentum":
                if ticker not in self.momentum._entry_tstat:
                    self.momentum._entry_tstat[ticker] = pending_tstat.get(ticker) or 0.0

        # Heal any held without origin
        for ticker, pos in self.held_positions.items():
            if not pos.get("origin"):
                pos["origin"] = self._infer_origin(pos)

    def _check_buying_opportunity(self, ticker: str, prices: MarketPrices):
        # Routed via update_ticker_price
        pass

    def _check_exit_conditions(self, ticker: str, prices: MarketPrices):
        # Routed via update_ticker_price
        pass
