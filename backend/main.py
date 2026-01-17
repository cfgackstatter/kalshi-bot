from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from kalshi_client import KalshiTrader
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from strategy import HighProbStrategy

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

trader = KalshiTrader()

def _safe_parse_datetime(dt_string):
    """Parse datetime string handling variable microsecond precision."""
    if not isinstance(dt_string, str):
        return dt_string

    dt_string = dt_string.replace("Z", "+00:00")

    # Handle microseconds - Python expects 0, 3, or 6 digits
    if '.' in dt_string and ('+' in dt_string or dt_string.count('-') > 2):
        parts = dt_string.split('.')
        if len(parts) == 2:
            date_part = parts[0]
            micro_and_tz = parts[1]

            if '+' in micro_and_tz:
                micro, tz = micro_and_tz.split('+')
                micro = micro.ljust(6, '0')[:6]
                dt_string = f"{date_part}.{micro}+{tz}"
            elif '-' in micro_and_tz and micro_and_tz.index('-') > 2:
                # Last '-' is timezone separator
                idx = micro_and_tz.rindex('-')
                micro = micro_and_tz[:idx]
                tz = micro_and_tz[idx+1:]
                micro = micro.ljust(6, '0')[:6]
                dt_string = f"{date_part}.{micro}-{tz}"

    dt = datetime.fromisoformat(dt_string)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

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
        close_time = _safe_parse_datetime(close_time)
        
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
        close_time = _safe_parse_datetime(market.close_time)
        
        time_left = close_time - now
        days = time_left.days
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        total_seconds = time_left.total_seconds()
        
        markets_data[market.ticker] = {
            "last_price": getattr(market, "last_price", getattr(market, "yes_ask", 50)),
            "yes_bid": getattr(market, "yes_bid", 0),
            "yes_ask": getattr(market, "yes_ask", 0),
            "no_bid": getattr(market, "no_bid", 0),
            "no_ask": getattr(market, "no_ask", 0),
            "days_left": days,
            "hours_left": hours,
            "minutes_left": minutes,
            "total_seconds_left": total_seconds,
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
            "total_seconds_left": 0,
        })
        
        contracts = pos.position
        total_cost = float(pos.market_exposure_dollars)
        fees_paid = float(pos.fees_paid_dollars)
        cost_with_fees = total_cost + fees_paid
        avg_price_with_fees = (cost_with_fees / abs(contracts) * 100) if contracts != 0 else 0
        
        # Determine side based on position sign (positive = yes, negative = no)
        side = "yes" if contracts > 0 else "no"
        contracts = abs(contracts)
        
        # Use appropriate bid for market value calculation
        current_bid = market_info["yes_bid"] if side == "yes" else market_info["no_bid"]
        
        payout_if_right = contracts * 1.0
        market_value = contracts * current_bid / 100
        unrealized_return = market_value - cost_with_fees
        
        positions.append({
            "ticker": pos.ticker,
            "side": side,
            "current_bid": current_bid,
            "contracts": contracts,
            "avg_price": avg_price_with_fees,
            "cost": cost_with_fees,
            "payout_if_right": payout_if_right,
            "market_value": market_value,
            "unrealized_return": unrealized_return,
            "days_left": market_info["days_left"],
            "hours_left": market_info["hours_left"],
            "minutes_left": market_info["minutes_left"],
            "total_seconds_left": market_info["total_seconds_left"],
            "yes_bid": market_info["yes_bid"],
            "yes_ask": market_info["yes_ask"],
            "no_bid": market_info["no_bid"],
            "no_ask": market_info["no_ask"],
        })
    
    positions.sort(key=lambda p: p["total_seconds_left"])
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


# Global strategy state
scheduler = AsyncIOScheduler()
strategy_config = {
    "capital_allocation": 50,
    "position_size": 5,
    "min_probability": 98,
    "scan_frequency": 15,
    "stop_loss": 50,
    "max_time_to_expiry": 1,
    "max_pending_age_minutes": 5,
    "order_delay_seconds": 0.5,
    "max_spread": 2,
    "min_volume": 1,
    "enabled": False
}
strategy = HighProbStrategy(trader, strategy_config)

@app.on_event("startup")
async def startup_event():
    scheduler.start()

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()

@app.post("/api/strategy/start")
def start_strategy():
    strategy_config["enabled"] = True
    strategy.config = strategy_config  # Update config
    
    # Remove existing job if any
    if scheduler.get_job("strategy_scan"):
        scheduler.remove_job("strategy_scan")
    if scheduler.get_job("strategy_exits"):
        scheduler.remove_job("strategy_exits")
    
    # Schedule scanning
    scheduler.add_job(
        strategy.scan_and_execute,
        "interval",
        minutes=strategy_config["scan_frequency"],
        id="strategy_scan"
    )
    
    # Schedule exit monitoring (every 5 min)
    scheduler.add_job(
        strategy.check_stop_losses,
        "interval",
        minutes=5,
        id="strategy_exits"
    )
    
    try:
        strategy.scan_and_execute()
    except Exception as e:
        print(f"Initial scan failed: {e}")
    
    return {"success": True, "status": "started"}

@app.post("/api/strategy/stop")
def stop_strategy():
    strategy_config["enabled"] = False
    
    if scheduler.get_job("strategy_scan"):
        scheduler.remove_job("strategy_scan")
    if scheduler.get_job("strategy_exits"):
        scheduler.remove_job("strategy_exits")
    
    return {"success": True, "status": "stopped"}

@app.put("/api/strategy/config")
def update_config(config: dict):
    strategy_config.update(config)
    strategy.config = strategy_config
    
    # Restart if running
    if strategy_config["enabled"]:
        stop_strategy()
        start_strategy()
    
    return {"success": True, "config": strategy_config}