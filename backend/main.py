import os
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from kalshi_client import KalshiTrader
from websocket_client import KalshiWebSocket
from market_utils import market_time_info, format_position, is_illiquid, MarketPrices
from strategies.bonding_strategy import BondingStrategy
from strategies.momentum_strategy import MomentumStrategy, momentum_signal
from config.defaults import STRATEGY_DEFAULTS, BONDING_DEFAULTS

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

def _rotating(path: str, level: int) -> RotatingFileHandler:
    h = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=2)
    h.setLevel(level)
    h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    return h

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        _rotating("logs/bot_errors.log", logging.WARNING),
        _rotating("logs/trades.log", logging.INFO),
        logging.StreamHandler(),
    ],
)
# Silence noisy third-party loggers from trades.log
logging.getLogger("uvicorn").propagate = False
logging.getLogger("apscheduler").propagate = False
logging.getLogger("httpx").propagate = False

logger = logging.getLogger(__name__)

# ── App state ─────────────────────────────────────────────────────────────────
STRATEGY_CLASSES = {"bonding": BondingStrategy, "momentum": MomentumStrategy}

trader          = KalshiTrader()
scheduler       = AsyncIOScheduler()
ws_client       = None
strategy_config = dict(BONDING_DEFAULTS)           # single source of truth
strategy        = BondingStrategy(trader, strategy_config)

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global ws_client
    scheduler.start()
    ws_client = KalshiWebSocket(trader, lambda ticker_data: strategy.update_ticker_price(ticker_data))
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
        now    = datetime.now(timezone.utc)
        max_ts = int((now + timedelta(hours=1)).timestamp())
        result = []
        for m in trader.get_markets(status="open", max_close_ts=max_ts):
            if is_illiquid(MarketPrices.from_market(m)):
                continue
            result.append({
                "ticker":        m.ticker,
                "title":         getattr(m, "title", m.ticker),
                "subtitle":      getattr(m, "subtitle", ""),
                "yes_sub_title": getattr(m, "yes_sub_title", ""),
                "no_sub_title":  getattr(m, "no_sub_title", ""),
                "volume":        getattr(m, "volume", 0) or 0,
                "open_interest": getattr(m, "open_interest", 0) or 0,
                **market_time_info(m, now),
            })
        result.sort(key=lambda m: m["total_seconds_left"])
        return {"markets": result, "count": len(result)}
    except Exception as e:
        logger.error(f"Markets error: {e}")
        return {"markets": [], "count": 0, "error": str(e)}

@app.get("/api/orders")
def get_orders():
    try:
        orders = trader.get_orders(status="resting") or []
        return {"orders": [{
            "order_id":       o.order_id,
            "ticker":         o.ticker,
            "side":           o.side,
            "action":         o.action,
            "price":          getattr(o, f"{o.side}_price", 0),
            "remaining_count": o.remaining_count,
            "initial_count":  o.initial_count,
            "created_time":   o.created_time,
        } for o in orders], "count": len(orders)}
    except Exception as e:
        logger.error(f"Orders error: {e}")
        return {"orders": [], "count": 0, "error": str(e)}

@app.get("/api/positions")
def get_positions():
    try:
        positions = getattr(trader.get_positions(), "market_positions", [])
        if not positions:
            return {"positions": [], "count": 0}
        now         = datetime.now(timezone.utc)
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
    if req.side not in ("yes", "no"):   raise HTTPException(400, "Side must be 'yes' or 'no'")
    if req.quantity <= 0:               raise HTTPException(400, "Quantity must be positive")
    if not (1 <= req.price <= 99):      raise HTTPException(400, "Price must be 1–99")

@app.post("/api/trade")
def execute_trade(req: TradeRequest):
    try:
        _validate_trade(req)
        return {"success": True, "order": trader.create_order(
            ticker=req.ticker, side=req.side, quantity=req.quantity, price=req.price)}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/api/close")
def close_position(req: TradeRequest):
    try:
        _validate_trade(req)
        return {"success": True, "order": trader.close_position(
            ticker=req.ticker, side=req.side, quantity=req.quantity, price=req.price)}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/api/cancel")
def cancel_order(req: CancelRequest):
    try:
        return {"success": True, "result": trader.cancel_order(req.order_id)}
    except Exception as e: raise HTTPException(500, str(e))

# ── Strategy endpoints ────────────────────────────────────────────────────────
@app.post("/api/strategy/start")
async def start_strategy():
    global strategy
    strategy_config["enabled"] = True
    cls = STRATEGY_CLASSES.get(strategy_config.get("strategy_type", "bonding"), BondingStrategy)

    if not isinstance(strategy, cls):
        strategy = cls(trader, strategy_config)
        if isinstance(strategy, MomentumStrategy):
            strategy.price_history.clear()
    else:
        strategy.config = strategy_config
        # Do NOT clear price_history — preserve momentum window

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
    if strategy_config.get("enabled") and scheduler.get_job("scan"):
        scheduler.reschedule_job("scan", trigger="interval", minutes=strategy_config["scan_frequency"])
    return {"success": True, "config": strategy_config}

@app.get("/api/strategy/defaults/{strategy_type}")
def get_defaults(strategy_type: str):
    if strategy_type not in STRATEGY_DEFAULTS:
        raise HTTPException(404, "Unknown strategy type")
    return STRATEGY_DEFAULTS[strategy_type]

# ── Scheduler task ────────────────────────────────────────────────────────────
_listen_task: asyncio.Task | None = None

async def scan_and_subscribe():
    global _listen_task

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
        # Cancel previous listen task before reconnecting
        if _listen_task and not _listen_task.done():
            _listen_task.cancel()
            try:
                await _listen_task
            except asyncio.CancelledError:
                pass

        if ws_client.ws:
            await ws_client.ws.close()
            ws_client.ws = None
        await asyncio.sleep(0.5)
        await ws_client.connect()
        _listen_task = asyncio.create_task(ws_client.listen())
        await ws_client.subscribe_tickers(all_tickers)
        logger.info(f"Monitoring {len(all_tickers)} tickers ({len(strategy.held_positions)} positions)")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

# ── Debugging endpoint ─────────────────────────────────────────────────────────
@app.get("/api/debug/momentum")
def get_momentum_debug():
    if not isinstance(strategy, MomentumStrategy):
        return {"error": "Not running momentum strategy"}
    result = {}
    for ticker, history in strategy.price_history.items():
        if len(history) < 2:
            continue
        slope_cpm, tstat = momentum_signal(history)
        result[ticker] = {
            "points":      len(history),
            "window_secs": round((history[-1][0] - history[0][0]).total_seconds(), 1),
            "slope_cpm":   round(slope_cpm, 3),
            "tstat":       round(tstat, 3),
            "history":     [{"t": ts.isoformat(), "mid": mid} for ts, mid in history],
        }
    return dict(sorted(result.items(), key=lambda x: abs(x[1]["tstat"]), reverse=True))
