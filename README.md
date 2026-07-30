# Kalshi Trading Bot

Automated trading bot for Kalshi prediction markets with real-time WebSocket price monitoring and a React dashboard.

## Features

- **Real-time monitoring** via Kalshi WebSocket API
- **Automated trading strategies** (bonding + momentum) with configurable parameters
- **Stop-loss protection** with configurable thresholds
- **Web dashboard** for portfolio management and manual trading
- **Resilient error handling** with retry logic and logging

## Quick Start

### One-time setup
```bash
make install
```

Create `backend/.env`:
```text
KALSHI_API_KEY=your_api_key
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_BASE_URL=https://api.elections.kalshi.com
```

### Run (backend + frontend)
```bash
make
```

This starts the API on `:8000` and the dashboard on `:3000`. Ctrl+C stops both.

Or run them separately:
```bash
make backend    # FastAPI — http://localhost:8000
make frontend   # Vite    — http://localhost:3000
```

Access the dashboard at `http://localhost:3000`

## Configuration

Adjust strategy parameters in the dashboard or via API. Defaults live in `backend/config/defaults.py`.

## Project Structure

```text
backend/
├── main.py                 # FastAPI server & endpoints
├── config/                 # Strategy default configs
├── strategies/             # Bonding & momentum strategies
├── kalshi_client.py        # Kalshi API wrapper
├── websocket_client.py     # Real-time price feed
└── market_utils.py         # Pricing & position helpers

frontend/
├── src/
│   ├── App.jsx             # Main dashboard
│   └── App.css             # Styling
```
