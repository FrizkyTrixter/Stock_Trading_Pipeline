"""Leakage-aware features preserving the prototype's target and embargo semantics."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZON = 50
TARGET_RETURN = 0.10
EMBARGO_SESSIONS = 50


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    formula: str
    lookback: int
    inputs: tuple[str, ...]
    missing_behavior: str = "null until lookback is complete"


FEATURE_DEFINITIONS = (
    FeatureDefinition("Return_1d", "close.pct_change(1)", 1, ("Close",)),
    FeatureDefinition("Return_5d", "close.pct_change(5)", 5, ("Close",)),
    FeatureDefinition("Return_10d", "close.pct_change(10)", 10, ("Close",)),
    FeatureDefinition("Return_20d", "close.pct_change(20)", 20, ("Close",)),
    FeatureDefinition("Momentum_200d", "close / close.shift(200) - 1", 200, ("Close",)),
    FeatureDefinition("RSI_14", "100 - 100/(1 + rolling_gain/rolling_loss)", 14, ("Close",)),
    FeatureDefinition("MACD", "EMA(12) - EMA(26)", 26, ("Close",)),
    FeatureDefinition("Volatility_20d", "rolling_std(Return_1d, 20)", 20, ("Close",)),
    FeatureDefinition("Dollar_Volume", "Close * Volume", 1, ("Close", "Volume")),
)


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    return 100 - (100 / (1 + gain / loss))


def build_features(frame: pd.DataFrame, include_labels: bool = True) -> pd.DataFrame:
    output: list[pd.DataFrame] = []
    for _ticker, group in frame.groupby("Ticker", sort=True):
        group = group.sort_values("Date").copy()
        group["Return_1d"] = group["Close"].pct_change()
        for window in (5, 10, 20):
            group[f"Return_{window}d"] = group["Close"].pct_change(window)
        for window in (5, 10, 20, 50, 100, 200):
            group[f"SMA_{window}"] = group["Close"].rolling(window).mean()
            group[f"Close_to_SMA_{window}"] = group["Close"] / group[f"SMA_{window}"] - 1
        group["Momentum_200d"] = group["Close"] / group["Close"].shift(200) - 1
        group["Volatility_10d"] = group["Return_1d"].rolling(10).std()
        group["Volatility_20d"] = group["Return_1d"].rolling(20).std()
        group["RSI_14"] = rsi(group["Close"])
        ema12 = group["Close"].ewm(span=12, adjust=False).mean()
        ema26 = group["Close"].ewm(span=26, adjust=False).mean()
        group["MACD"] = ema12 - ema26
        group["MACD_signal"] = group["MACD"].ewm(span=9, adjust=False).mean()
        group["MACD_hist"] = group["MACD"] - group["MACD_signal"]
        group["Volume_Change_5d"] = group["Volume"].pct_change(5)
        group["Dollar_Volume"] = group["Close"] * group["Volume"]
        if include_labels:
            future_max = group["Close"].shift(-1).rolling(HORIZON).max().shift(-(HORIZON - 1))
            group["Future_Max_Return_50d"] = future_max / group["Close"] - 1
            group["Target"] = np.where(
                group["Future_Max_Return_50d"].notna(),
                (group["Future_Max_Return_50d"] >= TARGET_RETURN).astype(int),
                np.nan,
            )
        output.append(group)
    if not output:
        raise ValueError("No market data supplied")
    return pd.concat(output, ignore_index=True).replace([np.inf, -np.inf], np.nan)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {
        "Date",
        "Ticker",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Future_Max_Return_50d",
        "Target",
    }
    return [column for column in frame.columns if column not in excluded]


def leakage_audit(frame: pd.DataFrame, columns: list[str]) -> tuple[str, ...]:
    findings: list[str] = []
    forbidden = {"Target", "Future_Max_Return_50d", "future", "label"}
    for column in columns:
        lowered = column.casefold()
        if column in forbidden or "future" in lowered or lowered == "label":
            findings.append(f"forbidden_feature:{column}")
    if frame[columns].isna().all(axis=0).any():
        findings.extend(
            f"all_null_feature:{name}"
            for name in frame[columns].columns[frame[columns].isna().all()]
        )
    return tuple(findings)


def chronological_split_dates(
    dates: list[pd.Timestamp],
    train_days: int,
    validation_days: int,
    embargo: int = EMBARGO_SESSIONS,
) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
    required = train_days + validation_days + embargo
    if len(dates) < required:
        raise ValueError(f"Need {required} dates, found {len(dates)}")
    validation = dates[-validation_days:]
    train_end = len(dates) - validation_days - embargo
    training = dates[train_end - train_days : train_end]
    if training[-1] >= validation[0]:
        raise AssertionError("chronological split invariant failed")
    return training, validation
