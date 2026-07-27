# Kalshi Trading Bot

Automated trading bot for Kalshi prediction markets with real-time WebSocket price monitoring and a React dashboard.

## Features

- **Real-time monitoring** via Kalshi WebSocket API
- **Automated trading strategy** for high-probability short-term markets
- **Stop-loss protection** with configurable thresholds
- **Web dashboard** for portfolio management and manual trading
- **Resilient error handling** with retry logic and logging

## Quick Start

### Backend
```bash
cd backend
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
python -m uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install  # first time only
npm run dev
```

Access the dashboard at `http://localhost:3000`

## Configuration

Create `backend/.env`:
```text
KALSHI_API_KEY=your_api_key
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_BASE_URL=https://api.elections.kalshi.com
```

Adjust strategy parameters in the dashboard or via API.

## Project Structure

```text
backend/
├── main.py              # FastAPI server & endpoints
├── strategy.py          # Trading strategy logic
├── kalshi_client.py     # Kalshi API wrapper
├── websocket_client.py  # Real-time price feed
└── utils.py             # Helpers & retry logic

frontend/
├── src/
│   ├── App.jsx          # Main dashboard
│   └── App.css          # Styling
```