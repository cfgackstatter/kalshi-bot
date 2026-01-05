from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from kalshi_client import KalshiTrader

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

trader = KalshiTrader()


class OrderRequest(BaseModel):
    ticker: str
    side: str  # "yes" or "no"
    quantity: int
    price: Optional[int] = None  # cents, None = market order


@app.get("/api/balance")
def get_balance():
    """Get account balance."""
    return trader.get_balance()


@app.get("/api/markets")
def get_markets(
    min_yes_ask: Optional[int] = Query(None, ge=0, le=100),
    max_yes_ask: Optional[int] = Query(None, ge=0, le=100),
    min_yes_bid: Optional[int] = Query(None, ge=0, le=100),
    max_yes_bid: Optional[int] = Query(None, ge=0, le=100),
    max_days: Optional[int] = Query(None, ge=0),
    min_volume: Optional[int] = Query(None, ge=0)
):
    """
    Get filtered markets by raw API fields.
    
    Query params:
        min_yes_ask: Minimum yes ask price in cents (for buying yes)
        max_yes_ask: Maximum yes ask price in cents
        min_yes_bid: Minimum yes bid price in cents
        max_yes_bid: Maximum yes bid price in cents (for almost-sure bets)
        max_days: Maximum days until close
        min_volume: Minimum volume (liquidity filter)
    """
    markets_response = trader.get_markets(status="open", limit=200)
    markets = []
    
    now = datetime.now(timezone.utc)
    
    for market in markets_response.markets:
        # Parse market data - close_time might be datetime or string
        close_time = market.close_time
        if isinstance(close_time, str):
            close_time = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
        
        # Ensure close_time is timezone-aware
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        
        days_left = (close_time - now).days
        
        yes_bid = market.yes_bid if hasattr(market, 'yes_bid') and market.yes_bid else 0
        yes_ask = market.yes_ask if hasattr(market, 'yes_ask') and market.yes_ask else 0
        volume = market.volume if hasattr(market, 'volume') else 0
        
        # Apply filters on raw API fields only
        if min_yes_ask is not None and yes_ask < min_yes_ask:
            continue
        if max_yes_ask is not None and yes_ask > max_yes_ask:
            continue
        if min_yes_bid is not None and yes_bid < min_yes_bid:
            continue
        if max_yes_bid is not None and yes_bid > max_yes_bid:
            continue
        if max_days is not None and days_left > max_days:
            continue
        if min_volume is not None and volume < min_volume:
            continue
        
        markets.append({
            "ticker": market.ticker,
            "title": market.title if hasattr(market, 'title') else market.ticker,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": market.no_bid if hasattr(market, 'no_bid') else 0,
            "no_ask": market.no_ask if hasattr(market, 'no_ask') else 0,
            "volume": volume,
            "open_interest": market.open_interest if hasattr(market, 'open_interest') else 0,
            "close_time": close_time.isoformat(),
            "days_left": days_left,
            "category": market.category if hasattr(market, 'category') else "Unknown"
        })
    
    return {"markets": markets, "count": len(markets)}


@app.get("/api/positions")
def get_positions():
    """Get all current positions with P&L."""
    positions_response = trader.get_positions()
    positions = []
    
    for pos in positions_response.positions if hasattr(positions_response, 'positions') else []:
        # Calculate P&L
        position_value = pos.position * pos.market_price / 100 if hasattr(pos, 'market_price') else 0
        cost_basis = pos.position * pos.avg_price / 100 if hasattr(pos, 'avg_price') else 0
        pnl = position_value - cost_basis
        
        positions.append({
            "ticker": pos.ticker,
            "side": pos.side if hasattr(pos, 'side') else "yes",
            "quantity": pos.position,
            "avg_price": pos.avg_price / 100 if hasattr(pos, 'avg_price') else 0,
            "current_price": pos.market_price / 100 if hasattr(pos, 'market_price') else 0,
            "pnl": pnl,
            "pnl_pct": (pnl / cost_basis * 100) if cost_basis > 0 else 0
        })
    
    return {"positions": positions, "count": len(positions)}


@app.post("/api/orders/create")
def create_order(order: OrderRequest):
    """Create a new order (buy)."""
    try:
        result = trader.create_order(
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            price=order.price
        )
        return {"status": "success", "order": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/orders/close")
def close_position(ticker: str, side: str, quantity: int):
    """Close a position (sell)."""
    try:
        result = trader.close_position(ticker, side, quantity)
        return {"status": "success", "order": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
