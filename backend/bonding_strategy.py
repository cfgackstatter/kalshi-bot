from datetime import datetime, timezone, timedelta
from base_strategy import BaseStrategy
from market_utils import MarketPrices, is_illiquid, is_profitable, kalshi_fee
import logging

logger = logging.getLogger(__name__)


def kelly_contracts(order_price: int, edge: float, portfolio: float,
                    kelly_fraction: float, max_pct: float, available_cash: float) -> int:
    implied_prob = order_price / 100
    odds         = max(1 - implied_prob, 0.01)
    kelly        = edge / odds
    safe_kelly   = min(kelly * kelly_fraction, max_pct)
    capital      = portfolio * max(safe_kelly, 0.005)

    price_dollars  = order_price / 100
    desired        = round(capital / price_dollars)
    max_affordable = int(available_cash / price_dollars)

    if max_affordable < 1:
        return 0                          # can't afford even 1 contract — hard stop

    return max(min(desired, max_affordable), 1)   # at least 1, but only if affordable


class BondingStrategy(BaseStrategy):
    """
    High-probability bonding strategy.
    Buys YES or NO contracts trading near certainty (default ≥96¢)
    and exits at take-profit or stop-loss.
    """

    def scan_markets(self) -> list[str]:
        now           = datetime.now(timezone.utc)
        max_close_ts  = int((now + timedelta(hours=self.config["max_time_to_expiry"])).timestamp())
        markets       = self.trader.get_markets(status="open", max_close_ts=max_close_ts)

        eligible = []
        for market in markets:
            if self._passes_filters(market):
                self.monitored_markets[market.ticker] = market
                eligible.append(market.ticker)

        logger.info(f"[Bonding] Scan: {len(eligible)} eligible markets")
        return eligible

    # ── Private ─────────────────────────────────────────────────────────────

    def _passes_filters(self, market) -> bool:
        excludes = self.config.get("ticker_exclude_substrings", "")
        if excludes:
            parts = [s.strip().lower() for s in excludes.split(",") if s.strip()]
            if any(p in market.ticker.lower() for p in parts):
                return False

        prices = MarketPrices.from_market(market)
        return not is_illiquid(prices) and (getattr(market, "volume", 0) or 0) > 0

    def _check_buying_opportunity(self, ticker: str, prices: MarketPrices):
        markets = self.trader.get_markets(tickers=[ticker])
        if not markets:
            return
        market = markets[0]

        for side in ["yes", "no"]:
            if self._should_buy(ticker, side, prices, market):
                self._execute_buy(ticker, side, prices)
                break  # one side per ticker only

    def _should_buy(self, ticker: str, side: str, prices: MarketPrices, market) -> bool:
        if ticker in self.held_positions:
            return False
        bid, ask = prices.for_side(side)
        mid      = (bid + ask) / 2
        return (
            (ask - bid)                            <= self.config.get("max_spread", 99)
            and mid                                >= self.config["min_probability"]
            and (getattr(market, "volume", 0) or 0) >= self.config.get("min_volume", 0)
        )

    def _execute_buy(self, ticker: str, side: str, prices: MarketPrices):
        now = datetime.now(timezone.utc)
        last_attempt = self.buy_attempts.get(ticker)
        if last_attempt and (now - last_attempt).total_seconds() < 10:
            return

        bid, _  = prices.for_side(side)
        maker   = self.config.get("order_at_bid", False)
        order_price = max(bid, 1) if maker else min(bid + 1, 99)

        balance         = self.trader.get_balance()
        total_portfolio = balance["balance"] + balance["portfolio_value"]
        available_cash  = balance["balance"]

        contracts = kelly_contracts(
            order_price    = order_price,
            edge           = self.config.get("estimated_edge", 0.02),
            portfolio      = total_portfolio,
            kelly_fraction = self.config.get("kelly_fraction", 0.25),
            max_pct        = self.config.get("max_position_pct", 0.05),
            available_cash = available_cash,
        )

        if contracts < 1:
            return

        # Profitability gate: use taker fee (worst case) regardless of order mode.
        # If unprofitable even at the cheaper maker rate this would never pass,
        # and if it passes taker it's guaranteed profitable under any fill classification.
        if not is_profitable(contracts, order_price, maker=False):
            logger.debug(
                f"SKIP {ticker} {side}: {contracts}x{order_price}¢ unprofitable at taker fee "
                f"(gross={contracts * (100 - order_price) / 100 * 100:.1f}¢ "
                f"fee={kalshi_fee(contracts, order_price, maker=False) * 100:.1f}¢)"
            )
            return

        total_cost   = contracts * order_price / 100
        expected_fee = kalshi_fee(contracts, order_price, maker=maker)  # optimistic for logging
        worst_fee    = kalshi_fee(contracts, order_price, maker=False)
        net_if_win   = contracts * (100 - order_price) / 100 - worst_fee  # conservative net

        self.buy_attempts[ticker] = now
        try:
            self.trader.create_order(
                ticker=ticker, side=side, quantity=contracts, price=order_price
            )
            self.held_positions[ticker] = {
                "side":        side,
                "contracts":   contracts,
                "entry_price": order_price,
                "entry_time":  now.isoformat(),
            }
            self.monitored_markets.pop(ticker, None)
            self.buy_attempts.pop(ticker, None)
            logger.info(
                f"[Bonding] BUY {contracts} {side} @ {order_price}¢ on {ticker} | "
                f"cost=${total_cost:.2f} "
                f"fee=${expected_fee:.4f}({'maker' if maker else 'taker'}) "
                f"worst_net_if_win=${net_if_win:.4f}"
            )
        except Exception as e:
            self.buy_attempts.pop(ticker, None)
            logger.error(f"[Bonding] Buy failed for {ticker}: {e}")

    def _check_exit_conditions(self, ticker: str, prices: MarketPrices):
        position    = self.held_positions[ticker]
        side        = position["side"]
        bid, ask    = prices.for_side(side)
        spread      = ask - bid
        mid         = (bid + ask) / 2
        entry_price = position.get("entry_price") or mid

        # Take-profit: full payout
        if bid >= 100:
            logger.info(f"[Bonding] TAKE-PROFIT (100¢): {ticker} {side}")
            self.close_position(ticker, position, prices)
            return

        # Take-profit: 99¢ only if entered below 99¢
        if bid >= 99 and entry_price <= 98:
            logger.info(f"[Bonding] TAKE-PROFIT: {ticker} {side} "
                        f"bid={bid}¢ entry={entry_price}¢ profit={bid - entry_price:+}¢")
            self.close_position(ticker, position, prices)
            return

        # Stop-loss
        max_loss = self.config.get("max_loss_percent", 0.30)
        if mid < entry_price * (1 - max_loss):
            loss_pct = (entry_price - mid) / entry_price * 100
            logger.warning(f"[Bonding] STOP-LOSS: {ticker} {side} "
                           f"entry={entry_price}¢ mid={mid:.1f}¢ loss={loss_pct:.1f}%")
            self.close_position(ticker, position, prices)
            return

        # Emergency: wide spread and deeply underwater
        if spread >= 50 and mid < entry_price * 0.85:
            logger.error(f"[Bonding] EMERGENCY EXIT: {ticker} {side} mid={mid:.1f}¢ spread={spread}¢")
            self.close_position(ticker, position, prices, emergency=True)
