from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone, timedelta

from kalshi_client import KalshiTrader

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

trader = KalshiTrader()


@app.get("/api/balance")
def get_balance():
    """Get account balance."""
    return trader.get_balance()


@app.get("/api/markets")
def get_markets():
    """Get all markets closing within 72 hours, sorted by time remaining."""
    now = datetime.now(timezone.utc)
    max_close_time = now + timedelta(hours=72)
    max_close_ts = int(max_close_time.timestamp())
    
    all_markets = trader.get_all_markets(status="open", max_close_ts=max_close_ts)
    markets = []
    
    for market in all_markets:
        close_time = market.close_time
        if isinstance(close_time, str):
            close_time = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)

        time_left = close_time - now
        days = time_left.days
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        total_seconds = time_left.total_seconds()

        yes_bid = getattr(market, "yes_bid", 0) or 0
        yes_ask = getattr(market, "yes_ask", 0) or 0
        no_bid = getattr(market, "no_bid", 0) or 0
        no_ask = getattr(market, "no_ask", 0) or 0

        if yes_ask >= 100 or yes_ask <= 0 or yes_bid >= 100 or yes_bid <= 0:
            continue

        markets.append({
            "ticker": market.ticker,
            "title": getattr(market, "title", market.ticker),
            "subtitle": getattr(market, "subtitle", ""),
            "yes_sub_title": getattr(market, "yes_sub_title", ""),
            "no_sub_title": getattr(market, "no_sub_title", ""),
            "category": getattr(market, "category", "Unknown"),
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "volume": getattr(market, "volume", 0) or 0,
            "open_interest": getattr(market, "open_interest", 0) or 0,
            "close_time": close_time.isoformat(),
            "days_left": days,
            "hours_left": hours,
            "minutes_left": minutes,
            "total_seconds_left": total_seconds,
        })

    markets.sort(key=lambda m: m["total_seconds_left"])
    return {"markets": markets, "count": len(markets)}


@app.get("/api/positions")
def get_positions():
    """Get current positions with P&L."""
    positions_response = trader.get_positions()
    positions = []

    for pos in getattr(positions_response, "positions", []):
        position_value = (
            pos.position * pos.market_price / 100 if hasattr(pos, "market_price") else 0
        )
        cost_basis = (
            pos.position * pos.avg_price / 100 if hasattr(pos, "avg_price") else 0
        )
        pnl = position_value - cost_basis

        positions.append({
            "ticker": pos.ticker,
            "side": getattr(pos, "side", "yes"),
            "quantity": pos.position,
            "avg_price": (pos.avg_price / 100) if hasattr(pos, "avg_price") else 0,
            "current_price": (pos.market_price / 100)
            if hasattr(pos, "market_price")
            else 0,
            "pnl": pnl,
        })

    return {"positions": positions, "count": len(positions)}