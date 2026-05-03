import gzip
import os
import random
import re
import sqlite3
import time
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from html.parser import HTMLParser

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from delay_model import get_predictor, ROUTES, AIRCRAFT_TYPES

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "flights.db")
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_no TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL,
            dep_time TEXT NOT NULL, arr_time TEXT NOT NULL, aircraft TEXT NOT NULL,
            status TEXT DEFAULT 'ON TIME', delay_min INTEGER DEFAULT 0,
            wind_speed REAL DEFAULT 10.0, temperature REAL DEFAULT 20.0,
            visibility REAL DEFAULT 8.0
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0] == 0:
        _seed_flights(conn)
    conn.commit()
    conn.close()


def _seed_flights(conn: sqlite3.Connection):
    rng = random.Random(2024)
    base = datetime(2025, 6, 1, 6, 0)
    rows = []
    for i, (origin, dest) in enumerate(ROUTES * 3):
        dep = base + timedelta(hours=i * 2 + rng.randint(0, 1))
        dur = timedelta(hours=rng.randint(2, 6), minutes=rng.choice([0, 15, 30, 45]))
        arr = dep + dur
        delay = rng.choices([0, rng.randint(10, 120)], weights=[0.7, 0.3])[0]
        rows.append((
            f"SZ{100 + i}", origin, dest,
            dep.strftime("%Y-%m-%dT%H:%M"), arr.strftime("%Y-%m-%dT%H:%M"),
            rng.choice(AIRCRAFT_TYPES),
            "DELAYED" if delay > 0 else "ON TIME", delay,
            round(rng.uniform(5, 55), 1), round(rng.uniform(-15, 42), 1),
            round(rng.uniform(0.5, 10), 1),
        ))
    conn.executemany(
        "INSERT INTO flights (flight_no,origin,destination,dep_time,arr_time,"
        "aircraft,status,delay_min,wind_speed,temperature,visibility) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?)", rows,
    )


# ── Somon Air flightboard scraper ─────────────────────────────────────────────

_BOARD_URL = "https://www.somonair.com/en/flightboard"
_board_cache: dict = {"data": None, "ts": 0.0}
_BOARD_TTL = 300  # 5 min

_IATA_RE = re.compile(r'\b([A-Z]{3})\b')

_STATUS_MAP = {
    "arrived":        ("arrived",   "ПРИБЫЛ"),
    "arrival":        ("arrived",   "ПРИБЫЛ"),
    "departed":       ("departed",  "ВЫЛЕТЕЛ"),
    "departure":      ("departing", "ВЫЛЕТ"),
    "en route":       ("en_route",  "В ПУТИ"),
    "pending":        ("scheduled", "ОЖИДАНИЕ"),
    "delayed":        ("delayed",   "ЗАДЕРЖАН"),
    "cancelled":      ("cancelled", "ОТМЕНЁН"),
    "прибыл":         ("arrived",   "ПРИБЫЛ"),
    "приземлился":    ("arrived",   "ПРИБЫЛ"),
    "вылетел":        ("departed",  "ВЫЛЕТЕЛ"),
    "вылет":          ("departing", "ВЫЛЕТ"),
    "по расписанию":  ("scheduled", "ОЖИДАНИЕ"),
    "задержан":       ("delayed",   "ЗАДЕРЖАН"),
    "в пути":         ("en_route",  "В ПУТИ"),
    "отменён":        ("cancelled", "ОТМЕНЁН"),
}

_CITY_RU = {
    "DYU": "Душанбе",    "LBD": "Худжанд",    "TJU": "Куляб",
    "DME": "Москва",     "SVO": "Москва",     "ZIA": "Москва",
    "VKO": "Москва",     "LED": "СПб",        "SVX": "Екатеринбург",
    "KZN": "Казань",     "OVB": "Новосибирск","KJA": "Красноярск",
    "IST": "Стамбул",    "DXB": "Дубай",      "DEL": "Дели",
    "TAS": "Ташкент",    "NQZ": "Астана",     "ALA": "Алматы",
    "URC": "Урумчи",     "SGC": "Сургут",     "UFA": "Уфа",
    "KUF": "Самара",     "IKA": "Тегеран",    "JED": "Джидда",
    "MUC": "Мюнхен",     "FRU": "Бишкек",
}


class _FlightTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._active = False
        self._depth = 0
        self._in_row = self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "table":
            if d.get("id") == "flightTable" or "flight" in d.get("class", "").lower():
                self._active = True
                self._depth = 1
                return
            if self._active:
                self._depth += 1
        if not self._active:
            return
        if tag == "tr":
            self._row = []; self._in_row = True
        elif tag in ("td", "th") and self._in_row:
            self._cell = []; self._in_cell = True

    def handle_endtag(self, tag):
        if not self._active:
            return
        if tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self._active = False
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._row.append(" ".join(self._cell).strip())
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._row:
                self.rows.append(self._row[:])

    def handle_data(self, data):
        if self._in_cell and (t := data.strip()):
            self._cell.append(t)


def _iata(text: str) -> str:
    m = _IATA_RE.search(text)
    return m.group(1) if m else text.strip()[:3].upper()


def _split_daytime(s: str) -> tuple[str, str]:
    parts = s.split()
    if parts and not parts[0][0].isdigit():
        return " ".join(parts[:-1]), parts[-1]
    return "", s


def _parse_status(raw: str) -> tuple[str, str]:
    lower = raw.lower()
    for key, val in _STATUS_MAP.items():
        if key in lower:
            return val
    return "scheduled", raw.upper()[:12]


def fetch_flightboard() -> list[dict]:
    now = time.time()
    if _board_cache["data"] is not None and now - _board_cache["ts"] < _BOARD_TTL:
        return _board_cache["data"]

    req = urllib.request.Request(
        _BOARD_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read()
        enc = resp.getheader("Content-Encoding", "")
    html = gzip.decompress(raw).decode("utf-8", errors="replace") if "gzip" in enc else raw.decode("utf-8", errors="replace")

    parser = _FlightTableParser()
    parser.feed(html)

    flights = []
    for i, row in enumerate(parser.rows):
        if len(row) < 4 or not re.search(r'SZ\s*\d', row[0]):
            continue
        fn = re.sub(r'\s+', ' ', row[0]).strip()
        org = _iata(row[1])
        dst = _iata(row[2])
        dep_day, dep_t = _split_daytime(row[3])
        _, arr_t = _split_daytime(row[4] if len(row) > 4 else "—")
        status_raw = " ".join(row[5:]).strip() if len(row) > 5 else "—"
        st_type, st_label = _parse_status(status_raw)
        flights.append({
            "id": i,
            "flight_no": fn,
            "origin": org,
            "origin_city": _CITY_RU.get(org, org),
            "destination": dst,
            "destination_city": _CITY_RU.get(dst, dst),
            "dep_time": dep_t,
            "dep_day": dep_day,
            "arr_time": arr_t,
            "status": st_label,
            "status_type": st_type,
        })

    _board_cache["data"] = flights
    _board_cache["ts"] = now
    return flights


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_predictor()
    yield


app = FastAPI(title="Somon Air MVP", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/api/flightboard")
def flightboard():
    try:
        data = fetch_flightboard()
        cached_at = datetime.fromtimestamp(_board_cache["ts"]).strftime("%H:%M:%S") if _board_cache["ts"] else None
        return {"flights": data, "total": len(data), "cached_at": cached_at, "source": "somonair.com"}
    except Exception as exc:
        return {"flights": [], "total": 0, "error": str(exc), "source": "somonair.com"}


@app.get("/api/flights")
def list_flights():
    conn = get_db()
    rows = conn.execute("SELECT * FROM flights ORDER BY dep_time").fetchall()
    conn.close()
    return [dict(r) for r in rows]


class PredictRequest(BaseModel):
    origin: str
    destination: str
    dep_hour: int
    aircraft: str
    wind_speed: float
    temperature: float
    visibility: float
    is_weekend: int = 0


@app.post("/api/predict")
def predict_delay(req: PredictRequest):
    return get_predictor().predict(
        origin=req.origin, destination=req.destination,
        dep_hour=req.dep_hour, aircraft=req.aircraft,
        wind_speed=req.wind_speed, temperature=req.temperature,
        visibility=req.visibility, is_weekend=req.is_weekend,
    )


@app.get("/api/stats")
def stats():
    conn = get_db()
    total   = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    delayed = conn.execute("SELECT COUNT(*) FROM flights WHERE status='DELAYED'").fetchone()[0]
    avg_d   = conn.execute("SELECT AVG(delay_min) FROM flights WHERE delay_min>0").fetchone()[0] or 0
    routes  = conn.execute("SELECT COUNT(DISTINCT origin||destination) FROM flights").fetchone()[0]
    conn.close()
    return {
        "total_flights": total, "delayed_flights": delayed,
        "on_time_rate": round((total - delayed) / total * 100, 1) if total else 0,
        "avg_delay_min": round(avg_d, 1), "routes": routes,
    }
