# train_xgboost_model_market_data.py
# pip install pandas numpy scikit-learn xgboost joblib pyarrow
#
# This version DOES NOT download from Stooq.
# It uses the market data produced by your GitHub Action:
#
#     data/raw/market_data.parquet
#
# Expected market data format, one row per ticker per date:
# Date, Ticker, Open, High, Low, Close, Volume
#
# The loader is deliberately tolerant of slightly different capitalization
# and common yfinance column names.

import argparse
import json
import os
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from xgboost import XGBClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)


START = "2015-01-01"
END = None
TRAIN_DAYS = 200
VALIDATION_DAYS = 50
HORIZON = 50
TARGET_RETURN = 0.10
PROBA_THRESHOLD = 0.50
MAX_POSITIONS = 20

DEFAULT_UNIVERSE_FILE = "src/agents/ticker_universe.json"
DEFAULT_OUTPUT_DIR = "data/predictions"
DEFAULT_MODEL_DIR = "data/processed"
DEFAULT_MARKET_DATA_FILE = "data/raw/market_data.parquet"


def rsi(series, window=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def load_tickers_from_json(path):
    """
    Accepts either:
    1. Full universe JSON: {"tickers": [{"ticker": "NVDA", ...}, ...]}
    2. Plain ticker list JSON: ["NVDA", "AMD", ...]
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "tickers" in data:
        tickers = []
        for item in data["tickers"]:
            if isinstance(item, dict) and "ticker" in item:
                tickers.append(str(item["ticker"]).strip().upper())
            elif isinstance(item, str):
                tickers.append(item.strip().upper())
    elif isinstance(data, list):
        tickers = [str(x).strip().upper() for x in data]
    else:
        raise ValueError("JSON must be either {'tickers': [...]} or a plain list of ticker strings.")

    seen = set()
    clean = []
    for ticker in tickers:
        if ticker and ticker not in seen:
            clean.append(ticker)
            seen.add(ticker)

    if not clean:
        raise ValueError(f"No tickers found in {path}")

    return clean


def _flatten_columns(df):
    """
    Handles normal columns and accidental MultiIndex columns.
    Example MultiIndex yfinance columns become Close_NVDA, Volume_NVDA, etc.
    This script mostly expects already-flat long-format data, but this prevents
    weird crashes if a file was saved with MultiIndex columns.
    """
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "_".join([str(x) for x in col if str(x) != ""]).strip("_")
            for col in df.columns
        ]
    return df


def _find_column(df, candidates):
    """
    Case-insensitive column finder.
    """
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def _standardize_market_data_columns(df):
    """
    Converts your saved market data into the exact columns used by the model:
    Date, Ticker, Open, High, Low, Close, Volume
    """
    df = _flatten_columns(df).copy()

    # Sometimes parquet/csv files preserve an index as a real column.
    unnamed = [c for c in df.columns if str(c).lower().startswith("unnamed")]
    if unnamed:
        df = df.drop(columns=unnamed)

    date_col = _find_column(df, ["Date", "Datetime", "date", "datetime", "index"])
    ticker_col = _find_column(df, ["Ticker", "ticker", "Symbol", "symbol"])

    open_col = _find_column(df, ["Open", "open"])
    high_col = _find_column(df, ["High", "high"])
    low_col = _find_column(df, ["Low", "low"])
    close_col = _find_column(df, ["Close", "close", "Adj Close", "adj close", "Adj_Close", "adj_close"])
    volume_col = _find_column(df, ["Volume", "volume"])

    required = {
        "Date": date_col,
        "Ticker": ticker_col,
        "Open": open_col,
        "High": high_col,
        "Low": low_col,
        "Close": close_col,
        "Volume": volume_col,
    }
    missing = [name for name, col in required.items() if col is None]
    if missing:
        raise ValueError(
            "Market data file is missing required columns: "
            f"{missing}\nAvailable columns: {list(df.columns)}"
        )

    out = df[[date_col, ticker_col, open_col, high_col, low_col, close_col, volume_col]].copy()
    out.columns = ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]

    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["Ticker"] = out["Ticker"].astype(str).str.strip().str.upper()

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])
    out = out[out["Ticker"] != ""]
    out = out.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    out = out.sort_values(["Ticker", "Date"]).reset_index(drop=True)

    if out.empty:
        raise RuntimeError("Market data loaded successfully, but no usable OHLCV rows remained after cleaning.")

    return out


def load_market_data(market_data_file, tickers=None, start=START, end=END):
    """
    Loads the already-downloaded market data file.

    Supported file types:
    - .parquet / .pq
    - .csv

    This is the key change from the Stooq version:
    no API calls, no requests, no redownloading.
    """
    if not os.path.exists(market_data_file):
        raise FileNotFoundError(
            f"Market data file not found: {market_data_file}\n"
            "Run this first from your repo root:\n"
            "  git pull\n"
            "Then confirm the file exists:\n"
            "  ls -lh data/raw/market_data.parquet"
        )

    ext = os.path.splitext(market_data_file)[1].lower()
    if ext in [".parquet", ".pq"]:
        raw = pd.read_parquet(market_data_file)
    elif ext == ".csv":
        raw = pd.read_csv(market_data_file)
    else:
        raise ValueError(
            f"Unsupported market data file type: {ext}. "
            "Use .parquet or .csv."
        )

    prices = _standardize_market_data_columns(raw)

    if tickers is not None:
        tickers = [str(t).strip().upper() for t in tickers]
        prices = prices[prices["Ticker"].isin(tickers)].copy()

    if start:
        prices = prices[prices["Date"] >= pd.Timestamp(start)].copy()
    if end:
        prices = prices[prices["Date"] <= pd.Timestamp(end)].copy()

    if prices.empty:
        raise RuntimeError(
            "No market data remained after filtering by universe/start/end. "
            "Check your ticker universe and date filters."
        )

    return prices


def add_indicators(df):
    out = []

    for ticker, g in df.groupby("Ticker"):
        g = g.sort_values("Date").copy()

        g["Return_1d"] = g["Close"].pct_change()
        g["Return_5d"] = g["Close"].pct_change(5)
        g["Return_10d"] = g["Close"].pct_change(10)
        g["Return_20d"] = g["Close"].pct_change(20)

        for w in [5, 10, 20, 50, 100, 200]:
            g[f"SMA_{w}"] = g["Close"].rolling(w).mean()
            g[f"Close_to_SMA_{w}"] = g["Close"] / g[f"SMA_{w}"] - 1

        g["Momentum_200d"] = g["Close"] / g["Close"].shift(200) - 1

        g["Volatility_10d"] = g["Return_1d"].rolling(10).std()
        g["Volatility_20d"] = g["Return_1d"].rolling(20).std()
        g["RSI_14"] = rsi(g["Close"], 14)

        ema12 = g["Close"].ewm(span=12, adjust=False).mean()
        ema26 = g["Close"].ewm(span=26, adjust=False).mean()

        g["MACD"] = ema12 - ema26
        g["MACD_signal"] = g["MACD"].ewm(span=9, adjust=False).mean()
        g["MACD_hist"] = g["MACD"] - g["MACD_signal"]

        g["Volume_Change_5d"] = g["Volume"].pct_change(5)
        g["Dollar_Volume"] = g["Close"] * g["Volume"]

        future_max = (
            g["Close"]
            .shift(-1)
            .rolling(HORIZON)
            .max()
            .shift(-(HORIZON - 1))
        )

        g["Future_Max_Return_50d"] = future_max / g["Close"] - 1
        g["Target"] = np.where(
            g["Future_Max_Return_50d"].notna(),
            (g["Future_Max_Return_50d"] >= TARGET_RETURN).astype(int),
            np.nan,
        )

        out.append(g)

    if not out:
        raise RuntimeError("No ticker data available. Cannot build indicators.")

    return pd.concat(out, ignore_index=True)


def make_features(df):
    ignore = {
        "Date", "Ticker", "Open", "High", "Low", "Close", "Volume",
        "Future_Max_Return_50d", "Target"
    }
    return [c for c in df.columns if c not in ignore]


def create_xgb_model(device="cuda"):
    return XGBClassifier(
        n_estimators=250,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        device=device,
        random_state=42,
    )


def classification_metrics(y_true, predictions, probabilities, prefix):
    """Return JSON-safe classification metrics with a consistent prefix."""
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    metrics = {
        f"{prefix}_rows": int(len(y_true)),
        f"{prefix}_positive_rate": float(y_true.mean()),
        f"{prefix}_accuracy": float(accuracy_score(y_true, predictions)),
        f"{prefix}_precision": float(precision_score(y_true, predictions, zero_division=0)),
        f"{prefix}_recall": float(recall_score(y_true, predictions, zero_division=0)),
        f"{prefix}_TP": int(tp),
        f"{prefix}_TN": int(tn),
        f"{prefix}_FP": int(fp),
        f"{prefix}_FN": int(fn),
    }
    # ROC AUC is undefined when a split contains only one target class.
    metrics[f"{prefix}_roc_auc"] = (
        float(roc_auc_score(y_true, probabilities)) if y_true.nunique() == 2 else None
    )
    majority_rate = max(float(y_true.mean()), 1.0 - float(y_true.mean()))
    metrics[f"{prefix}_majority_baseline_accuracy"] = majority_rate
    metrics[f"{prefix}_accuracy_vs_baseline"] = metrics[f"{prefix}_accuracy"] - majority_rate
    return metrics


def json_safe(value):
    """Convert model metadata to strict JSON (no NaN or NumPy values)."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def train_latest_model(
    panel,
    feature_cols,
    train_days=TRAIN_DAYS,
    validation_days=VALIDATION_DAYS,
    embargo_days=HORIZON,
    device="cuda",
):
    """Validate chronologically, then fit a production model on recent labels.

    The embargo prevents a training row's forward 50-day label window from
    overlapping the validation period. This is essential for an honest result.
    """
    dates = sorted(panel["Date"].dropna().unique())
    latest_prediction_date = dates[-1]

    trainable = panel.dropna(subset=feature_cols + ["Target"]).copy()
    trainable_dates = sorted(trainable["Date"].dropna().unique())

    required_dates = train_days + validation_days + embargo_days
    if len(trainable_dates) < required_dates:
        raise RuntimeError(
            f"Not enough trainable dates. Need at least {required_dates} "
            f"({train_days} train + {embargo_days} embargo + "
            f"{validation_days} validation), found {len(trainable_dates)}. "
            "Try an earlier --start date or fewer indicator windows."
        )

    validation_dates = trainable_dates[-validation_days:]
    validation_start_index = len(trainable_dates) - validation_days
    train_end_index = validation_start_index - embargo_days
    evaluation_train_dates = trainable_dates[train_end_index - train_days:train_end_index]

    evaluation_train = trainable[trainable["Date"].isin(evaluation_train_dates)].copy()
    validation = trainable[trainable["Date"].isin(validation_dates)].copy()

    X_train = evaluation_train[feature_cols]
    y_train = evaluation_train["Target"].astype(int)
    X_validation = validation[feature_cols]
    y_validation = validation["Target"].astype(int)

    evaluation_model = create_xgb_model(device=device)
    evaluation_model.fit(X_train, y_train)

    validation_probabilities = evaluation_model.predict_proba(X_validation)[:, 1]
    validation_predictions = (validation_probabilities >= 0.5).astype(int)

    # After measuring out-of-sample performance, use the most recent labelled
    # observations to train the model that scores today's candidates.
    production_dates = trainable_dates[-train_days:]
    production_train = trainable[trainable["Date"].isin(production_dates)].copy()
    model = create_xgb_model(device=device)
    model.fit(production_train[feature_cols], production_train["Target"].astype(int))

    metrics = {
        "data_source": "local_market_data_file",
        "latest_prediction_date": str(pd.Timestamp(latest_prediction_date).date()),
        "target": f"maximum close return >= {TARGET_RETURN:.0%} in next {HORIZON} sessions",
        "evaluation_train_start_date": str(pd.Timestamp(evaluation_train_dates[0]).date()),
        "evaluation_train_end_date": str(pd.Timestamp(evaluation_train_dates[-1]).date()),
        "embargo_sessions": int(embargo_days),
        "validation_start_date": str(pd.Timestamp(validation_dates[0]).date()),
        "validation_end_date": str(pd.Timestamp(validation_dates[-1]).date()),
        "production_train_start_date": str(pd.Timestamp(production_dates[0]).date()),
        "production_train_end_date": str(pd.Timestamp(production_dates[-1]).date()),
        "production_train_rows": int(len(production_train)),
        "model_parameters": json_safe(model.get_params()),
    }
    metrics.update(
        classification_metrics(
            y_validation,
            validation_predictions,
            validation_probabilities,
            "validation",
        )
    )

    return model, metrics, latest_prediction_date


def predict_latest_buys(model, panel, feature_cols, pred_date, max_positions=MAX_POSITIONS, threshold=PROBA_THRESHOLD):
    pred_rows = panel[panel["Date"] == pred_date].copy()
    pred_rows = pred_rows.dropna(subset=feature_cols)

    if pred_rows.empty:
        return pd.DataFrame()

    pred_rows["Probability"] = model.predict_proba(pred_rows[feature_cols])[:, 1]
    picks = pred_rows[pred_rows["Probability"] >= threshold].copy()
    picks = picks.sort_values("Probability", ascending=False).head(max_positions)

    if picks.empty:
        return pd.DataFrame(columns=["Date", "Ticker", "Close", "Probability", "Suggested_Weight"])

    picks["Suggested_Weight"] = picks["Probability"] / picks["Probability"].sum()
    return picks[["Date", "Ticker", "Close", "Probability", "Suggested_Weight"]]


def save_outputs(model, picks, metrics, feature_cols, model_dir, output_dir):
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    model_path = os.path.join(model_dir, f"xgboost_model_market_data_{stamp}.joblib")
    picks_csv_path = os.path.join(output_dir, f"xgboost_buy_picks_market_data_{stamp}.csv")
    picks_json_path = os.path.join(output_dir, f"xgboost_buy_picks_market_data_{stamp}.json")
    metrics_path = os.path.join(output_dir, f"xgboost_train_metrics_market_data_{stamp}.json")
    feature_path = os.path.join(output_dir, f"xgboost_feature_columns_market_data_{stamp}.json")
    importance_path = os.path.join(output_dir, f"xgboost_feature_importance_market_data_{stamp}.csv")

    joblib.dump(model, model_path)
    picks.to_csv(picks_csv_path, index=False)

    picks_json = picks.copy()
    if not picks_json.empty:
        picks_json["Date"] = picks_json["Date"].astype(str)
    with open(picks_json_path, "w", encoding="utf-8") as f:
        json.dump(picks_json.to_dict(orient="records"), f, indent=2)

    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, allow_nan=False)

    with open(feature_path, "w", encoding="utf-8") as f:
        json.dump(feature_cols, f, indent=2)

    feature_importance = pd.DataFrame(
        {"Feature": feature_cols, "Importance": model.feature_importances_}
    ).sort_values("Importance", ascending=False)
    feature_importance.to_csv(importance_path, index=False)

    return {
        "model": model_path,
        "picks_csv": picks_csv_path,
        "picks_json": picks_json_path,
        "metrics": metrics_path,
        "feature_columns": feature_path,
        "feature_importance": importance_path,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Train XGBoost on your already-downloaded market_data.parquet and output current buy candidates."
    )
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE_FILE, help="Path to ticker_universe.json or plain ticker list JSON")
    parser.add_argument("--market-data-file", default=DEFAULT_MARKET_DATA_FILE, help="Path to data/raw/market_data.parquet")
    parser.add_argument("--start", default=START, help="Start date to use from market data")
    parser.add_argument("--end", default=END, help="End date to use from market data; default uses latest available")
    parser.add_argument("--train-days", type=int, default=TRAIN_DAYS)
    parser.add_argument("--validation-days", type=int, default=VALIDATION_DAYS)
    parser.add_argument("--threshold", type=float, default=PROBA_THRESHOLD)
    parser.add_argument("--max-positions", type=int, default=MAX_POSITIONS)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"], help="Use cuda if your XGBoost install/GPU supports it; otherwise use cpu")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)

    # Backward-compatible aliases so old commands do not instantly explode.
    # --cache-file now means the same thing as --market-data-file.
    parser.add_argument("--cache-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--refresh-data", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sleep-seconds", type=float, default=1.5, help=argparse.SUPPRESS)
    parser.add_argument("--max-retries", type=int, default=3, help=argparse.SUPPRESS)
    parser.add_argument("--exchange-suffix", default="us", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.cache_file:
        args.market_data_file = args.cache_file

    if args.refresh_data:
        print("Ignoring --refresh-data because this script uses local market data and does not download.")

    print("XGBoost version:", xgb.__version__)
    print(f"Using XGBoost device: {args.device}")

    tickers = load_tickers_from_json(args.universe)
    print(f"Loaded {len(tickers)} tickers from {args.universe}")

    print(f"Loading market data from {args.market_data_file}...")
    prices = load_market_data(
        market_data_file=args.market_data_file,
        tickers=tickers,
        start=args.start,
        end=args.end,
    )

    available = sorted(prices["Ticker"].unique()) if not prices.empty else []
    print(f"Using {len(available)} tickers with local market data.")
    print(f"Market data rows: {len(prices):,}")
    print(f"Date range: {prices['Date'].min().date()} to {prices['Date'].max().date()}")

    missing_from_file = sorted(set(tickers) - set(available))
    if missing_from_file:
        print(f"Warning: {len(missing_from_file)} universe tickers are missing from the market data file.")
        print("First missing tickers:", ", ".join(missing_from_file[:25]))

    print("Building technical indicators and labels...")
    panel = add_indicators(prices)
    panel = panel.replace([np.inf, -np.inf], np.nan)

    feature_cols = make_features(panel)

    print("Training latest XGBoost model...")
    model, metrics, pred_date = train_latest_model(
        panel=panel,
        feature_cols=feature_cols,
        train_days=args.train_days,
        validation_days=args.validation_days,
        embargo_days=HORIZON,
        device=args.device,
    )

    print("Scoring latest market date...")
    picks = predict_latest_buys(
        model=model,
        panel=panel,
        feature_cols=feature_cols,
        pred_date=pred_date,
        max_positions=args.max_positions,
        threshold=args.threshold,
    )

    paths = save_outputs(
        model=model,
        picks=picks,
        metrics=metrics,
        feature_cols=feature_cols,
        model_dir=args.model_dir,
        output_dir=args.output_dir,
    )

    print("\n========== TRAINING METRICS ==========")
    for k, v in metrics.items():
        print(f"{k}: {v}")

    print("\n========== CURRENT XGBOOST BUY CANDIDATES ==========")
    if picks.empty:
        print(f"No stocks passed probability threshold {args.threshold}.")
    else:
        print(picks.to_string(index=False))

    print("\nSaved files:")
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
