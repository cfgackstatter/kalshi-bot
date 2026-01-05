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
    min_prob: Optional[float] = Query(None, ge=0, le=1),
    max_prob: Optional[float] = Query(None, ge=0, le=1),
    max_days: Optional[int] = Query(None, ge=0),
    category: Optional[str] = None
):
    """
    Get filtered markets.
    
    Query params:
        min_prob: Minimum yes probability (0-1)
        max_prob: Maximum yes probability (0-1)
        max_days: Maximum days until close
        category: Market category filter
    """
    markets_response = trader.get_markets(status="open", limit=200)
    markets = []
    
    now = datetime.now(timezone.utc)
    
    for market in markets_response.markets:
        # Parse market data
        close_time = datetime.fromisoformat(market.close_time.replace('Z', '+00:00'))
        days_left = (close_time - now).days
        
        yes_prob = market.yes_bid / 100 if hasattr(market, 'yes_bid') and market.yes_bid else 0
        
        # Apply filters
        if min_prob and yes_prob < min_prob:
            continue
        if max_prob and yes_prob > max_prob:
            continue
        if max_days and days_left > max_days:
            continue
        if category and market.category != category:
            continue
        
        markets.append({
            "ticker": market.ticker,
            "title": market.title if hasattr(market, 'title') else market.ticker,
            "yes_bid": market.yes_bid if hasattr(market, 'yes_bid') else 0,
            "yes_ask": market.yes_ask if hasattr(market, 'yes_ask') else 0,
            "no_bid": market.no_bid if hasattr(market, 'no_bid') else 0,
            "no_ask": market.no_ask if hasattr(market, 'no_ask') else 0,
            "volume": market.volume if hasattr(market, 'volume') else 0,
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
