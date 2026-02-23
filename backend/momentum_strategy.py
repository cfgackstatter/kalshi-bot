from base_strategy import BaseStrategy
from market_utils import MarketPrices
import logging

logger = logging.getLogger(__name__)

class MomentumStrategy(BaseStrategy):
    """
    Buys markets showing strong directional price movement.
    Config keys: momentum_window, momentum_threshold, ...
    """

    def scan_markets(self) -> list[str]:
        # ... momentum-specific market scan
        pass

    def _check_buying_opportunity(self, ticker: str, prices: MarketPrices):
        # ... momentum entry logic
        pass

    def _check_exit_conditions(self, ticker: str, prices: MarketPrices):
        # ... momentum exit logic
        pass
    # close_position, update_positions, cleanup_pending_orders all inherited for free
