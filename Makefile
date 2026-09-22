SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command

.PHONY: dev backend frontend install test types clean

## Start both backend and frontend dev servers
dev:
	Start-Process powershell -ArgumentList "-NoProfile -Command `"cd backend; .venv\Scripts\activate; uvicorn app.main:app --reload --port 8000`""
	cd frontend; npm run dev

## Start backend only
backend:
	cd backend; .venv\Scripts\activate; uvicorn app.main:app --reload --port 8000

## Start frontend only
frontend:
	cd frontend; npm run dev

## Install all dependencies
install: install-backend install-frontend

install-backend:
	cd backend; python -m venv .venv; .venv\Scripts\activate; pip install -e ".[dev]"

install-frontend:
	cd frontend; npm install

## Run backend tests (MOCK_LLM=1 always)
test:
	cd backend; $env:MOCK_LLM="1"; $env:USE_SYNTHETIC_CARBON="1"; $env:SEED="42"; .venv\Scripts\activate; pytest -v

## Generate TypeScript types from OpenAPI schema
types:
	cd backend; .venv\Scripts\activate; uvicorn app.main:app --port 8001 &; Start-Sleep 2
	cd frontend; npx openapi-typescript http://localhost:8001/openapi.json -o src/api/types.gen.ts

## Clean build artifacts
clean:
	Remove-Item -Recurse -Force backend\.venv -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force backend\data\verdant.db -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force frontend\node_modules -ErrorAction SilentlyContinue
	Remove-Item -Recurse -Force frontend\dist -ErrorAction SilentlyContinue

## Seed telemetry DB with fake history (run after install)
seed:
	cd backend; .venv\Scripts\activate; python scripts/seed_telemetry.py

## Snapshot real carbon data for offline demo
snapshot-carbon:
	cd backend; .venv\Scripts\activate; python scripts/snapshot_carbon.py
