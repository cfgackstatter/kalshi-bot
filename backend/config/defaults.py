# config/defaults.py
# All default strategy configs live here.
# main.py imports these; the frontend fetches them via GET /api/strategy/defaults/{type}.

# Weather + entertainment noise — momentum especially bleeds fees here
_COMMON_EXCLUDES = (
    "MENTION-,SAY-,NETFLIX,ALBUM,SPOTIFY,SONG,"
    "LOWT,HIGHT,RAIN,KXHIGH,KXLOW,GOLDH,SILVERH,WTIH"
)

BONDING_DEFAULTS = {
    "strategy_type":           "bonding",
    # Entry: ask must be in [min_probability, 99] and stay there
    "min_probability":         98,
    "max_entry_ask":           98,      # 99¢ is fee-negative for 1-contract sizing
    "max_time_to_expiry":      0.25,    # 15 min — gives room for stability
    "max_spread":              2,
    "min_volume":              10,
    "ticker_exclude_substrings": _COMMON_EXCLUDES,
    # Ask must remain ≥ min_probability this long before entry (anti-spike)
    "stability_seconds":       60,
    # Residual edge after worst-case (taker) fees — 1¢ ok for single-contract 98¢
    "min_net_if_win_cents":    1,
    # Exposure caps
    "max_open_positions":      3,
    "max_positions_per_series": 1,      # series key groups BTC/BTCD/BTC15M together
    # Re-entry guards
    "rebuy_cooldown_seconds":  300,     # after close or buy attempt
    "buy_attempt_cooldown_seconds": 120,
    # Sizing
    "estimated_edge":          0.01,
    "kelly_fraction":          0.25,
    "max_position_pct":        0.05,
    # Exit: hold to settlement; only bail if mid collapses
    "hold_to_settlement":      True,
    "thesis_break_mid":        50,
    "min_take_profit_cents":   3,
    # Execution
    "order_at_bid":            False,
    # With ~5–15m windows, 3m maker floor starved taker fills — use ask when closer
    "maker_min_minutes_to_expiry": 0,
    "scan_frequency":          1,
    "max_pending_age_minutes": 1,
    "enabled":                 False,
}

MOMENTUM_DEFAULTS = {
    "strategy_type":             "momentum",
    "momentum_window_minutes":   8,
    "momentum_tstat_threshold":  4.0,
    "min_slope_cents_per_min":    0.75,
    "recent_window_seconds":     120,   # short-window slope must agree with full window
    "min_upside_cents":          10,
    "min_upside_ratio":          0.12,
    # Don't chase / don't trade bonding territory
    "max_entry_mid":             65,    # skip if side mid already > this
    "min_entry_price_cents":     25,
    "max_entry_price_cents":     65,
    # Wider exits + anti-whipsaw flip
    "take_profit_cents":         15,
    "stop_loss_cents":           10,
    "max_hold_minutes":          20,
    "exit_on_flip":              True,
    "flip_tstat_threshold":      3.5,
    "min_hold_seconds_before_flip": 180,
    "min_time_to_expiry":        2.0,
    "max_time_to_expiry":        12.0,
    "max_spread":                3,
    "min_volume":                100,
    "ticker_exclude_substrings": _COMMON_EXCLUDES,
    # Exposure
    "max_open_positions":        2,
    "max_positions_per_series":  1,
    "rebuy_cooldown_seconds":    600,
    "buy_attempt_cooldown_seconds": 180,
    # Sizing: base edge scaled by |t|/threshold up to edge_scale_cap
    "estimated_edge":            0.015,
    "edge_scale_cap":            1.5,
    "kelly_fraction":            0.15,
    "max_position_pct":          0.03,
    "order_at_bid":              False,
    "scan_frequency":            2,
    "max_pending_age_minutes":   2,
    "enabled":                   False,
}

def _leg_defaults(src: dict) -> dict:
    """Strategy-specific knobs only — shared risk lives on Combined top-level."""
    skip = {
        "strategy_type", "enabled", "scan_frequency", "max_pending_age_minutes",
        "max_open_positions", "max_positions_per_series", "kelly_fraction",
        "max_position_pct", "rebuy_cooldown_seconds", "buy_attempt_cooldown_seconds",
        "ticker_exclude_substrings", "order_at_bid",
    }
    return {k: v for k, v in src.items() if k not in skip}


COMBINED_DEFAULTS = {
    "strategy_type":             "combined",
    # Prefer bonding when available — momentum was bleeding on weather noise
    "prefer_mode":               "bonding_first",
    "score_hysteresis":          1.25,
    # Shared risk budget (tight)
    "max_open_positions":        2,
    "max_positions_per_series":  1,
    "kelly_fraction":            0.15,
    "max_position_pct":          0.03,
    "rebuy_cooldown_seconds":    600,
    "buy_attempt_cooldown_seconds": 180,
    "order_at_bid":              False,
    "ticker_exclude_substrings": _COMMON_EXCLUDES,
    "scan_frequency":            1,
    "max_pending_age_minutes":   2,
    "enabled":                   False,
    "bonding":                   _leg_defaults(BONDING_DEFAULTS),
    "momentum":                  _leg_defaults(MOMENTUM_DEFAULTS),
}

STRATEGY_DEFAULTS = {
    "bonding":  BONDING_DEFAULTS,
    "momentum": MOMENTUM_DEFAULTS,
    "combined": COMBINED_DEFAULTS,
}
