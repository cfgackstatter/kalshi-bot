# Kalshi bot — run from the repo root.
# Usage:  make          # start API + dashboard
#         make backend  # API only
#         make frontend # dashboard only
#         make install  # one-time deps

.PHONY: run backend frontend install help
.DEFAULT_GOAL := run

BACKEND_DIR  := backend
FRONTEND_DIR := frontend
# Path is relative to BACKEND_DIR after `cd`
PYTHON       := ./venv/bin/python3

# Start API + dashboard together (Ctrl+C stops both)
run:
	$(MAKE) -j2 backend frontend

# FastAPI on :8000 (hot reload)
backend:
	cd $(BACKEND_DIR) && $(PYTHON) -m uvicorn main:app --reload --port 8000

# Vite dashboard on :3000
frontend:
	cd $(FRONTEND_DIR) && npm run dev

# One-time setup: Python venv + npm packages
install:
	python3 -m venv $(BACKEND_DIR)/venv
	cd $(BACKEND_DIR) && $(PYTHON) -m pip install -r requirements.txt
	cd $(FRONTEND_DIR) && npm install

help:
	@echo "make / make run  — start backend (:8000) and frontend (:3000)"
	@echo "make backend     — API only"
	@echo "make frontend    — dashboard only"
	@echo "make install     — create venv, pip + npm install"
