from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from app.config import get_settings

settings = get_settings()
_model: IsolationForest | None = None


def _features(amount_minor: int, hour: int, currency_code: int) -> np.ndarray:
    return np.array([[np.log1p(amount_minor), hour, currency_code]], dtype=float)


def train_and_save(path: str | Path | None = None, n_samples: int = 5000) -> Path:
    path = Path(path or settings.fraud_model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    amounts = rng.lognormal(mean=8.5, sigma=1.0, size=n_samples)
    hours = rng.integers(0, 24, size=n_samples)
    currencies = rng.integers(0, 5, size=n_samples)
    x = np.column_stack([np.log1p(amounts), hours, currencies])
    model = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
    model.fit(x)
    joblib.dump(model, path)
    return path


def load_model() -> IsolationForest | None:
    global _model
    path = Path(settings.fraud_model_path)
    if not path.exists():
        return None
    _model = joblib.load(path)
    return _model


def score_payment(amount_minor: int, hour: int, currency: str) -> tuple[float, bool]:
    model = _model
    if model is None:
        model = load_model()
    if model is None:
        return 0.0, False
    currency_code = sum(ord(c) for c in currency.upper()) % 5
    raw = -float(model.score_samples(_features(amount_minor, hour, currency_code))[0])
    risk = float(1 / (1 + np.exp(-raw)))
    return risk, risk >= settings.fraud_threshold
