import asyncio
import logging
import requests
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from kalshi_client import KalshiTrader
from websocket_client import KalshiWebSocket
from market_utils import market_time_info, format_position, is_illiquid, MarketPrices
from bonding_strategy import BondingStrategy

# ── Logging ──────────────────────────────────────────────────────────────────

_file_handler = RotatingFileHandler("bot_errors.log", maxBytes=5 * 1024 * 1024, backupCount=2)
_file_handler.setLevel(logging.WARNING)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_file_handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)

# ── App state ─────────────────────────────────────────────────────────────────

trader    = KalshiTrader()
scheduler = AsyncIOScheduler()
ws_client = None

strategy_config = {
    "min_probability":           96,
    "max_entry_price":           97,
    "max_time_to_expiry":        0.25,
    "max_spread":                2,
    "min_volume":                1,
    "ticker_exclude_substrings": "MENTION-,SAY-,NETFLIX,ALBUM,SPOTIFY,SONG",
    "estimated_edge":            0.02,
    "kelly_fraction":            0.25,
    "max_position_pct":          0.05,
    "max_loss_percent":          0.30,
    "order_at_bid":              False,
    "scan_frequency":            1,
    "max_pending_age_minutes":   1,
    "enabled":                   False,
}

strategy = BondingStrategy(trader, strategy_config)

# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ws_client
    scheduler.start()
    ws_client = KalshiWebSocket(trader, strategy.update_ticker_price)
    asyncio.create_task(ws_client.run())
    logger.info("App started")
    yield
    scheduler.shutdown()
    if ws_client:
        await ws_client.close()
    logger.info("App shutdown")

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Request models ────────────────────────────────────────────────────────────

class TradeRequest(BaseModel):
    ticker: str
    side: str
    quantity: int
    price: int

class CancelRequest(BaseModel):
    order_id: str

# ── Market data endpoints ─────────────────────────────────────────────────────

@app.get("/api/balance")
def get_balance():
    try:
        return trader.get_balance()
    except Exception as e:
        logger.error(f"Balance error: {e}")
        return {"balance": 0, "portfolio_value": 0, "error": str(e)}


@app.get("/api/markets")
def get_markets():
    try:
        now      = datetime.now(timezone.utc)
        max_ts   = int((now + timedelta(hours=1)).timestamp())
        all_mkts = trader.get_markets(status="open", max_close_ts=max_ts)

        markets = []
        for m in all_mkts:
            info = market_time_info(m, now)
            if is_illiquid(MarketPrices.from_market(m)):
                continue
            markets.append({
                "ticker":        m.ticker,
                "title":         getattr(m, "title", m.ticker),
                "subtitle":      getattr(m, "subtitle", ""),
                "yes_sub_title": getattr(m, "yes_sub_title", ""),
                "no_sub_title":  getattr(m, "no_sub_title", ""),
                "volume":        getattr(m, "volume", 0) or 0,
                "open_interest": getattr(m, "open_interest", 0) or 0,
                **info,
            })

        markets.sort(key=lambda m: m["total_seconds_left"])
        return {"markets": markets, "count": len(markets)}
    except Exception as e:
        logger.error(f"Markets error: {e}")
        return {"markets": [], "count": 0, "error": str(e)}


@app.get("/api/orders")
def get_orders():
    try:
        orders = trader.get_orders(status="resting") or []
        return {"orders": [
            {
                "order_id":        o.order_id,
                "ticker":          o.ticker,
                "side":            o.side,
                "action":          o.action,
                "price":           getattr(o, f"{o.side}_price", 0),
                "remaining_count": o.remaining_count,
                "initial_count":   o.initial_count,
                "created_time":    o.created_time,
            }
            for o in orders
        ], "count": len(orders)}
    except Exception as e:
        logger.error(f"Orders error: {e}")
        return {"orders": [], "count": 0, "error": str(e)}


@app.get("/api/positions")
def get_positions():
    try:
        response  = trader.get_positions()
        positions = getattr(response, "market_positions", [])
        if not positions:
            return {"positions": [], "count": 0}

        now          = datetime.now(timezone.utc)
        markets_data = {
            m.ticker: market_time_info(m, now)
            for m in trader.get_markets(tickers=[p.ticker for p in positions])
        }
        fallback = {"yes_bid": 0, "yes_ask": 0, "no_bid": 0, "no_ask": 0,
                    "days_left": 0, "hours_left": 0, "minutes_left": 0, "total_seconds_left": 0}

        result = [format_position(p, markets_data.get(p.ticker, fallback)) for p in positions]
        result.sort(key=lambda p: p["total_seconds_left"])
        return {"positions": result, "count": len(result)}
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return {"positions": [], "count": 0, "error": str(e)}

# ── Trading endpoints ─────────────────────────────────────────────────────────

def _validate_trade(req: TradeRequest):
    if req.side not in ("yes", "no"):
        raise HTTPException(400, "Side must be 'yes' or 'no'")
    if req.quantity <= 0:
        raise HTTPException(400, "Quantity must be positive")
    if not (1 <= req.price <= 99):
        raise HTTPException(400, "Price must be 1–99")

@app.post("/api/trade")
def execute_trade(req: TradeRequest):
    try:
        _validate_trade(req)
        return {"success": True, "order": trader.create_order(
            ticker=req.ticker, side=req.side, quantity=req.quantity, price=req.price)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/close")
def close_position(req: TradeRequest):
    try:
        _validate_trade(req)
        return {"success": True, "order": trader.close_position(
            ticker=req.ticker, side=req.side, quantity=req.quantity, price=req.price)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/cancel")
def cancel_order(req: CancelRequest):
    try:
        return {"success": True, "result": trader.cancel_order(req.order_id)}
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Strategy management ───────────────────────────────────────────────────────

@app.post("/api/strategy/start")
async def start_strategy():
    strategy_config["enabled"] = True
    strategy.config = strategy_config
    if scheduler.get_job("scan"):
        scheduler.remove_job("scan")
    scheduler.add_job(scan_and_subscribe, "interval",
                      minutes=strategy_config["scan_frequency"], id="scan")
    try:
        await scan_and_subscribe()
    except Exception as e:
        logger.error(f"Initial scan failed: {e}")
    return {"success": True, "status": "started"}

@app.post("/api/strategy/stop")
def stop_strategy():
    strategy_config["enabled"] = False
    if scheduler.get_job("scan"):
        scheduler.remove_job("scan")
    return {"success": True, "status": "stopped"}

@app.get("/api/strategy/config")
def get_config():
    return strategy_config

@app.put("/api/strategy/config")
async def update_config(config: dict):
    strategy_config.update(config)
    strategy.config = strategy_config
    if strategy_config.get("enabled"):
        stop_strategy()
        await start_strategy()
    return {"success": True, "config": strategy_config}

# ── Scheduler task ────────────────────────────────────────────────────────────

async def scan_and_subscribe():
    try:
        strategy.cleanup_pending_orders()
        strategy.update_positions()
        eligible = strategy.scan_markets()
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        eligible = list(strategy.monitored_markets.keys())

    all_tickers = list(set(eligible + list(strategy.held_positions.keys())))
    if not (ws_client and all_tickers):
        return

    try:
        if ws_client.ws:
            await ws_client.ws.close()
            ws_client.ws = None
        await ws_client.connect()
        asyncio.create_task(ws_client.listen())
        await ws_client.subscribe_tickers(all_tickers)
        logger.info(f"Monitoring {len(all_tickers)} tickers "
                    f"({len(strategy.held_positions)} positions)")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
