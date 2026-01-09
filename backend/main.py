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


class CancelRequest(BaseModel):
    order_id: str


@app.get("/api/balance")
def get_balance():
    return trader.get_balance()


@app.get("/api/markets")
def get_markets():
    now = datetime.now(timezone.utc)
    max_close_time = now + timedelta(hours=72)
    max_close_ts = int(max_close_time.timestamp())
    all_markets = trader.get_markets(status="open", max_close_ts=max_close_ts)
    
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


@app.get("/api/orders")
def get_orders():
    orders = trader.get_orders(status="resting")
    
    order_list = []
    for order in orders:
        order_list.append({
            "order_id": order.order_id,
            "ticker": order.ticker,
            "side": order.side,
            "action": order.action,
            "price": getattr(order, f"{order.side}_price", 0),
            "remaining_count": order.remaining_count,
            "initial_count": order.initial_count,
            "created_time": order.created_time,
        })
    
    return {"orders": order_list, "count": len(order_list)}


@app.get("/api/positions")
def get_positions():
    positions_response = trader.get_positions()
    market_positions = getattr(positions_response, "market_positions", [])
    
    if not market_positions:
        return {"positions": [], "count": 0}
    
    tickers = [pos.ticker for pos in market_positions]
    markets_list = trader.get_markets(tickers=tickers)
    markets_data = {}
    now = datetime.now(timezone.utc)
    
    for market in markets_list:
        close_time = market.close_time
        if isinstance(close_time, str):
            close_time = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        
        time_left = close_time - now
        days = time_left.days
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        markets_data[market.ticker] = {
            "last_price": getattr(market, "last_price", getattr(market, "yes_ask", 50)),
            "yes_bid": getattr(market, "yes_bid", 0),
            "yes_ask": getattr(market, "yes_ask", 0),
            "no_bid": getattr(market, "no_bid", 0),
            "no_ask": getattr(market, "no_ask", 0),
            "days_left": days,
            "hours_left": hours,
            "minutes_left": minutes,
        }
    
    positions = []
    for pos in market_positions:
        market_info = markets_data.get(pos.ticker, {
            "last_price": 50,
            "yes_bid": 0,
            "yes_ask": 0,
            "no_bid": 0,
            "no_ask": 0,
            "days_left": 0,
            "hours_left": 0,
            "minutes_left": 0,
        })
        
        contracts = pos.position
        total_cost = float(pos.market_exposure_dollars)
        fees_paid = float(pos.fees_paid_dollars)
        cost_with_fees = total_cost + fees_paid
        avg_price_with_fees = (cost_with_fees / contracts * 100) if contracts != 0 else 0
        payout_if_right = contracts * 1.0
        market_value = contracts * market_info["last_price"] / 100
        unrealized_return = market_value - cost_with_fees
        
        positions.append({
            "ticker": pos.ticker,
            "last_price": market_info["last_price"],
            "contracts": contracts,
            "avg_price": avg_price_with_fees,
            "cost": cost_with_fees,
            "payout_if_right": payout_if_right,
            "market_value": market_value,
            "unrealized_return": unrealized_return,
            "days_left": market_info["days_left"],
            "hours_left": market_info["hours_left"],
            "minutes_left": market_info["minutes_left"],
            "yes_bid": market_info["yes_bid"],
            "yes_ask": market_info["yes_ask"],
            "no_bid": market_info["no_bid"],
            "no_ask": market_info["no_ask"],
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


@app.post("/api/cancel")
def cancel_order(request: CancelRequest):
    try:
        result = trader.cancel_order(request.order_id)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
