# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Somon Air MVP — авиационный дашборд с ML-прогнозом задержек рейсов для таджикской авиакомпании Somon Air.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start server (from backend/ directory)
cd backend && uvicorn main:app --reload --port 8000

# Or from project root
uvicorn backend.main:app --reload --port 8000 --app-dir .

# Access dashboard
# http://localhost:8000
```

## Architecture

```
somon-air-mvp/
├── backend/
│   ├── main.py          # FastAPI app — REST API + serves frontend
│   └── delay_model.py   # ML delay predictor (GradientBoosting, synthetic data)
├── frontend/
│   └── index.html       # Single-page dashboard (vanilla JS, no build step)
├── flights.db           # SQLite — auto-created on first run
├── backend/delay_model.pkl  # ML model cache — auto-created on first run
└── requirements.txt
```

### Backend (`backend/main.py`)

FastAPI app on port 8000. Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves `frontend/index.html` |
| GET | `/api/flights` | All flights from SQLite |
| GET | `/api/flights/{id}` | Single flight |
| POST | `/api/predict` | ML delay prediction |
| GET | `/api/stats` | Aggregate stats |

On startup (`lifespan`): creates SQLite DB + seeds 48 synthetic flights, loads or trains ML model.

### ML Model (`backend/delay_model.py`)

`DelayPredictor` wraps a `GradientBoostingClassifier` trained on 5000 synthetic records.

**Features:** origin, destination, departure hour, aircraft type, wind speed, temperature, visibility, is_weekend.

**Output:** `{ "probability": 0.0–1.0, "risk": "LOW" | "MEDIUM" | "HIGH" }` — LOW < 25%, MEDIUM 25–50%, HIGH > 50%.

Model is pickled to `backend/delay_model.pkl` and reloaded on subsequent startups (no re-training).

### Frontend (`frontend/index.html`)

Pure HTML/CSS/JS — no framework, no build step. Calls backend API at relative paths (`/api/...`).

- Stat cards — loaded from `/api/stats`
- Flights table — loaded from `/api/flights`, with per-flight ML risk fetched via `/api/predict`
- Predict panel — manual form → POST `/api/predict`

### Database

SQLite file `flights.db` created at project root. Schema: single `flights` table with columns: `id, flight_no, origin, destination, dep_time, arr_time, aircraft, status, delay_min, wind_speed, temperature, visibility`.

Seeded with 48 rows covering 16 routes (TJK hub: DME, DXB, IST, SVO, FRU, URC, KBL, TSE).

## Key Design Decisions

- The ML model is trained once and cached as a `.pkl` file. Delete `backend/delay_model.pkl` to force retraining.
- The frontend fetches ML predictions for every row in the table on page load (parallel `Promise.all`). For large datasets this should be batched.
- `uvicorn` must be started from inside `backend/` so relative paths to `flights.db` and `frontend/` resolve correctly.
