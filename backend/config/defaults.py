# config/defaults.py
# All default strategy configs live here.
# main.py imports these; the frontend fetches them via GET /api/strategy/config.
# App.jsx never hardcodes defaults — it always uses what the backend returns.

BONDING_DEFAULTS = {
    "strategy_type":           "bonding",
    # Entry filters
    "min_probability":         96,
    "max_time_to_expiry":      0.25,
    "max_spread":              2,
    "min_volume":              1,
    "ticker_exclude_substrings": "MENTION-,SAY-,NETFLIX,ALBUM,SPOTIFY,SONG",
    # Kelly sizing
    "estimated_edge":          0.02,
    "kelly_fraction":          0.25,
    "max_position_pct":        0.05,
    # Risk management
    "max_loss_percent":        0.30,
    # Execution
    "order_at_bid":            False,
    "scan_frequency":          1,
    "max_pending_age_minutes": 1,
    "enabled":                 False,
}

MOMENTUM_DEFAULTS = {
    "strategy_type":             "momentum",
    "momentum_window_minutes": 5,     # how far back to measure price move
    "momentum_tstat_threshold": 3.0,  # min regression t-stat to trigger entry
    "min_slope_cents_per_min": 1.0,
    "min_upside_cents":        10,     # min potential gain in cents at entry price
    "min_upside_ratio":        0.10,  # min upside/downside ratio at entry price
    "take_profit_cents":       10,     # exit when position up this many cents
    "stop_loss_cents":         10,     # exit when position down this many cents
    "max_hold_minutes":        30,    # force exit after this many minutes
    "min_time_to_expiry":      1.0,
    "max_time_to_expiry":      12.0,
    "max_spread":                2,
    "min_volume":                100,
    "ticker_exclude_substrings": "MENTION-,SAY-,NETFLIX,ALBUM,SPOTIFY,SONG",
    "estimated_edge":            0.02,
    "kelly_fraction":            0.25,
    "max_position_pct":          0.05,
    "max_loss_percent":          0.30,
    "order_at_bid":              False,
    "scan_frequency":            5,
    "max_pending_age_minutes":   2,
    "min_contract_price_cents":  10,
    "enabled":                   False,
}

STRATEGY_DEFAULTS = {
    "bonding":  BONDING_DEFAULTS,
    "momentum": MOMENTUM_DEFAULTS,
}
