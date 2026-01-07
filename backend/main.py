from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

from kalshi_client import KalshiTrader

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

trader = KalshiTrader()


class TradeRequest(BaseModel):
    ticker: str
    side: str
    quantity: int
    price: int


@app.get("/api/balance")
def get_balance():
    return trader.get_balance()


@app.get("/api/markets")
def get_markets():
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
    positions_response = trader.get_positions()
    market_positions = getattr(positions_response, "market_positions", [])
    
    positions = []
    for pos in market_positions:
        positions.append({
            "ticker": pos.ticker,
            "position": pos.position,
            "market_exposure": pos.market_exposure,
            "market_exposure_dollars": float(pos.market_exposure_dollars),
            "realized_pnl": pos.realized_pnl,
            "realized_pnl_dollars": float(pos.realized_pnl_dollars),
            "total_traded": pos.total_traded,
            "fees_paid": pos.fees_paid,
            "fees_paid_dollars": float(pos.fees_paid_dollars),
            "resting_orders_count": pos.resting_orders_count,
        })

    return {"positions": positions, "count": len(positions)}


@app.post("/api/trade")
def execute_trade(request: TradeRequest):
    try:
        if request.side not in ["yes", "no"]:
            raise HTTPException(status_code=400, detail="Side must be 'yes' or 'no'")
        if request.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")
        if request.price < 1 or request.price > 99:
            raise HTTPException(status_code=400, detail="Price must be between 1 and 99")
        
        result = trader.create_order(
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
            price=request.price
        )
        
        return {"success": True, "order": result}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/close")
def close_position(request: TradeRequest):
    try:
        if request.side not in ["yes", "no"]:
            raise HTTPException(status_code=400, detail="Side must be 'yes' or 'no'")
        if request.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")
        if request.price < 1 or request.price > 99:
            raise HTTPException(status_code=400, detail="Price must be between 1 and 99")
        
        result = trader.close_position(
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
            price=request.price
        )
        
        return {"success": True, "order": result}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
