import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder
import pickle
import os

ROUTES = [
    ("TJK", "DME"), ("DME", "TJK"), ("TJK", "DXB"), ("DXB", "TJK"),
    ("TJK", "IST"), ("IST", "TJK"), ("TJK", "SVO"), ("SVO", "TJK"),
    ("TJK", "FRU"), ("FRU", "TJK"), ("TJK", "URC"), ("URC", "TJK"),
    ("TJK", "KBL"), ("KBL", "TJK"), ("TJK", "TSE"), ("TSE", "TJK"),
]

AIRCRAFT_TYPES = ["B737", "A320", "B757", "A319"]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "delay_model.pkl")


def _generate_synthetic_data(n: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    routes = [ROUTES[i % len(ROUTES)] for i in rng.integers(0, len(ROUTES), n)]
    dep_hour = rng.integers(0, 24, n)
    aircraft = [AIRCRAFT_TYPES[i] for i in rng.integers(0, len(AIRCRAFT_TYPES), n)]
    wind_speed = rng.uniform(0, 60, n)
    temperature = rng.uniform(-20, 45, n)
    visibility = rng.uniform(0.5, 10, n)
    is_weekend = rng.integers(0, 2, n)

    # Delay probability logic
    p = (
        0.05
        + (dep_hour < 7).astype(float) * 0.15
        + (dep_hour > 20).astype(float) * 0.10
        + (wind_speed > 40).astype(float) * 0.25
        + (visibility < 2).astype(float) * 0.20
        + (temperature < -10).astype(float) * 0.10
        + is_weekend * 0.05
        + np.array([0.10 if a == "B757" else 0.0 for a in aircraft])
    )
    p = np.clip(p, 0, 1)
    delayed = rng.binomial(1, p, n)

    df = pd.DataFrame({
        "origin": [r[0] for r in routes],
        "destination": [r[1] for r in routes],
        "dep_hour": dep_hour,
        "aircraft": aircraft,
        "wind_speed": wind_speed,
        "temperature": temperature,
        "visibility": visibility,
        "is_weekend": is_weekend,
        "delayed": delayed,
    })
    return df


class DelayPredictor:
    def __init__(self):
        self.model: GradientBoostingClassifier | None = None
        self.origin_enc = LabelEncoder()
        self.dest_enc = LabelEncoder()
        self.aircraft_enc = LabelEncoder()
        self._fit_encoders()

    def _fit_encoders(self):
        origins = list({r[0] for r in ROUTES})
        dests = list({r[1] for r in ROUTES})
        self.origin_enc.fit(origins)
        self.dest_enc.fit(dests)
        self.aircraft_enc.fit(AIRCRAFT_TYPES)

    def _encode(self, df: pd.DataFrame) -> np.ndarray:
        return np.column_stack([
            self.origin_enc.transform(df["origin"]),
            self.dest_enc.transform(df["destination"]),
            df["dep_hour"].values,
            self.aircraft_enc.transform(df["aircraft"]),
            df["wind_speed"].values,
            df["temperature"].values,
            df["visibility"].values,
            df["is_weekend"].values,
        ])

    def train(self):
        df = _generate_synthetic_data()
        X = self._encode(df)
        y = df["delayed"].values
        self.model = GradientBoostingClassifier(n_estimators=200, max_depth=4, random_state=42)
        self.model.fit(X, y)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(self, f)
        return self

    def load_or_train(self):
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                loaded = pickle.load(f)
            self.model = loaded.model
            self.origin_enc = loaded.origin_enc
            self.dest_enc = loaded.dest_enc
            self.aircraft_enc = loaded.aircraft_enc
        else:
            self.train()
        return self

    def predict(
        self,
        origin: str,
        destination: str,
        dep_hour: int,
        aircraft: str,
        wind_speed: float,
        temperature: float,
        visibility: float,
        is_weekend: int,
    ) -> dict:
        df = pd.DataFrame([{
            "origin": origin,
            "destination": destination,
            "dep_hour": dep_hour,
            "aircraft": aircraft,
            "wind_speed": wind_speed,
            "temperature": temperature,
            "visibility": visibility,
            "is_weekend": is_weekend,
        }])
        X = self._encode(df)
        prob = float(self.model.predict_proba(X)[0][1])
        label = "HIGH" if prob > 0.5 else ("MEDIUM" if prob > 0.25 else "LOW")
        return {"probability": round(prob, 3), "risk": label}


_predictor: DelayPredictor | None = None


def get_predictor() -> DelayPredictor:
    global _predictor
    if _predictor is None:
        _predictor = DelayPredictor().load_or_train()
    return _predictor
