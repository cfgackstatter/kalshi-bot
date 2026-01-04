from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel
from typing import List
import json

from kalshi_client import KalshiTrader
from strategy import PremiumCollector
from db import Database

clients: List[WebSocket] = []
db = Database()
trader = KalshiTrader()
strategy = PremiumCollector(trader, db)

scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(strategy.run, 'interval', seconds=60)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

class StrategyParams(BaseModel):
    min_probability: float = 0.90
    max_time_to_close: int = 7
    position_size: float = 100.0
    kelly_fraction: float = 0.25

@app.get("/api/balance")
def get_balance():
    return trader.get_balance()

@app.get("/api/positions")
def get_positions():
    return db.get_positions()

@app.get("/api/trades")
def get_trades():
    return db.get_trades()

@app.get("/api/pnl")
def get_pnl():
    return db.get_pnl_summary()

@app.post("/api/strategy/params")
def update_params(params: StrategyParams):
    strategy.update_params(params.dict())
    return {"status": "updated"}

@app.get("/api/strategy/params")
def get_params():
    return strategy.get_params()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except:
        clients.remove(websocket)

async def broadcast_update(data: dict):
    for client in clients:
        try:
            await client.send_text(json.dumps(data))
        except:
            pass
