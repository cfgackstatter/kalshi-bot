import asyncio
import json
import logging
from typing import Callable
from websockets.asyncio.client import connect
from websockets.protocol import State
from kalshi_client import KalshiTrader

logger = logging.getLogger(__name__)


class KalshiWebSocket:
    def __init__(self, trader: KalshiTrader, on_ticker_update: Callable):
        self.trader = trader
        self.on_ticker_update = on_ticker_update
        self.ws = None
        self.message_id = 1
        self.running = False
        self._subscribed: set[str] = set()

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.ws.state is State.OPEN

    async def connect(self):
        """Establish authenticated WebSocket connection."""
        timestamp, signature = self.trader._create_auth(method="GET", path="/trade-api/ws/v2")
        headers = {
            "KALSHI-ACCESS-KEY": self.trader.api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

        ws_url = self.trader.base_url.replace("https://", "wss://") + "/trade-api/ws/v2"
        self.ws = await connect(ws_url, additional_headers=headers)
        self._subscribed.clear()

    async def subscribe_tickers(self, tickers: list[str]):
        """Subscribe to ticker updates for specific markets."""
        if not self.ws or not tickers:
            return

        msg = {
            "id": self.message_id,
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker"],
                "market_tickers": tickers,
            },
        }
        await self.ws.send(json.dumps(msg))
        self.message_id += 1
        self._subscribed.update(tickers)

    async def ensure_subscriptions(self, tickers: list[str]):
        """
        Keep the socket up and subscribe any new tickers.
        Avoids tearing down the connection every scan (which reset bonding stability).
        """
        wanted = set(tickers)
        if not self.connected:
            await self.connect()
            if wanted:
                await self.subscribe_tickers(sorted(wanted))
            return

        new = wanted - self._subscribed
        if new:
            await self.subscribe_tickers(sorted(new))

    async def listen(self):
        """Listen for ticker updates and invoke callback."""
        if not self.ws:
            logger.error("WebSocket not connected")
            return

        self.running = True
        try:
            async for message in self.ws:
                if not self.running:
                    break

                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "ticker":
                    ticker_data = data.get("msg", {})
                    self.on_ticker_update(ticker_data)
                elif msg_type == "error":
                    logger.error(f"WebSocket error: {data}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self.running = False
            # Don't close here on cancel — scan_and_subscribe owns reconnect lifecycle
            if self.ws and self.ws.state is not State.OPEN:
                self.ws = None
                self._subscribed.clear()
                logger.info("WebSocket closed")

    async def close(self):
        """Close WebSocket connection."""
        self.running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
            self._subscribed.clear()
            logger.info("WebSocket closed")

    async def run(self):
        """Connect and start listening."""
        await self.connect()
        await self.listen()
