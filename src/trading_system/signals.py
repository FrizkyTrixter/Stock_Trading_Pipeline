"""XGBoost inference adapter tied to a versioned universe."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import joblib
import pandas as pd

from .features import build_features, feature_columns


class XGBoostSignalService:
    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"Approved XGBoost artifact not found: {model_path}")
        self.model = joblib.load(model_path)
        self.model_version = model_path.stem

    def probabilities(self, frame: pd.DataFrame, tickers: tuple[str, ...]) -> dict[str, Decimal]:
        panel = build_features(frame, include_labels=False)
        columns = feature_columns(panel)
        output: dict[str, Decimal] = {}
        for ticker in tickers:
            rows = panel[panel["Ticker"] == ticker].dropna(subset=columns).sort_values("Date")
            if rows.empty:
                continue
            probability = self.model.predict_proba(rows.iloc[[-1]][columns])[0][1]
            output[ticker] = Decimal(str(float(probability)))
        return output


class FixedSignalService:
    """Deterministic test boundary."""

    model_version = "fixture-model"

    def __init__(self, values: dict[str, Decimal]) -> None:
        self.values = values

    def probabilities(self, frame: pd.DataFrame, tickers: tuple[str, ...]) -> dict[str, Decimal]:
        return {ticker: self.values[ticker] for ticker in tickers if ticker in self.values}
