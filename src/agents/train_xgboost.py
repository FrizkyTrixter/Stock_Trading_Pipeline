# train_xgboost_model_stooq.py
# pip install pandas numpy scikit-learn xgboost joblib

import argparse
import json
import os
import time
import warnings
from datetime import datetime
from urllib.parse import urlencode
from io import StringIO

import requests

warnings.filterwarnings("ignore")

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, confusion_matrix


START = "2015-01-01"
END = None
TRAIN_DAYS = 200
HORIZON = 50
TARGET_RETURN = 0.10
PROBA_THRESHOLD = 0.50
MAX_POSITIONS = 20

DEFAULT_UNIVERSE_FILE = "ticker_universe.json"
DEFAULT_OUTPUT_DIR = "data/predictions"
DEFAULT_MODEL_DIR = "data/processed"
DEFAULT_CACHE_FILE = "data/raw/stooq_market_data.csv"

STOOQ_BASE_URL = "https://stooq.com/q/d/l/"


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


def _date_to_stooq(value):
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%Y%m%d")


def ticker_to_stooq_symbol(ticker, exchange_suffix="us"):
    """
    Convert ordinary US tickers to Stooq symbols.

    Examples:
    NVDA  -> nvda.us
    BRK.B -> brk-b.us
    MOG.A -> mog-a.us

    Stooq commonly uses hyphens where Yahoo/other feeds use class-share dots.
    """
    t = str(ticker).strip().lower()
    t = t.replace(".", "-")
    return f"{t}.{exchange_suffix.lower()}"


def _download_one_stooq_ticker(ticker, start=START, end=END, exchange_suffix="us"):
    stooq_symbol = ticker_to_stooq_symbol(ticker, exchange_suffix=exchange_suffix)

    params = {
        "s": stooq_symbol,
        "i": "d",
        "d1": _date_to_stooq(start),
    }
    if end:
        params["d2"] = _date_to_stooq(end)

    url = f"{STOOQ_BASE_URL}?{urlencode(params)}"

    # Important: pandas.read_csv(url) uses urllib with a weak/default user-agent.
    # Stooq sometimes returns HTTP 404 to that, even for valid symbols like NVDA.US.
    # Fetch manually with a browser-like user-agent, then parse the CSV text.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"Failed {ticker} ({stooq_symbol}): HTTP {resp.status_code} | {url}")
            return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])

        text = resp.text.strip()
        if not text or text.lower().startswith("no data") or "Date" not in text.splitlines()[0]:
            print(f"No Stooq rows for {ticker} ({stooq_symbol})")
            return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])

        df = pd.read_csv(StringIO(text))
    except Exception as e:
        print(f"Failed {ticker} ({stooq_symbol}): {repr(e)}")
        return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])

    if df.empty or "Date" not in df.columns:
        print(f"No Stooq rows for {ticker} ({stooq_symbol})")
        return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])

    needed = ["Date", "Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        print(f"Skipping {ticker}: Stooq response missing columns {missing}")
        return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])

    df = df[needed].copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Ticker"] = ticker.upper()

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]]
    df = df.dropna(subset=["Date", "Open", "High", "Low", "Close", "Volume"])
    df = df.sort_values("Date")
    return df


def download_data(
    tickers,
    start=START,
    end=END,
    cache_file=DEFAULT_CACHE_FILE,
    refresh=False,
    sleep_seconds=1.5,
    max_retries=3,
    exchange_suffix="us",
):
    """
    Download daily OHLCV data from Stooq.

    Why this is safer than the yfinance version:
    - Stooq is queried one ticker at a time.
    - Results are cached to disk.
    - Existing cached tickers are skipped.
    - Failed tickers are retried with a simple backoff.

    Note: Stooq may not have every very recent IPO or speculative ticker.
    Any unavailable tickers are skipped and written to a missing-tickers file.
    """
    os.makedirs(os.path.dirname(cache_file) or ".", exist_ok=True)

    cached = pd.DataFrame()
    if os.path.exists(cache_file) and not refresh:
        print(f"Loading cached Stooq data from {cache_file}")
        cached = pd.read_csv(cache_file, parse_dates=["Date"])
        cached["Ticker"] = cached["Ticker"].astype(str).str.upper()
        cached_tickers = set(cached["Ticker"].unique())
        tickers_to_download = [t for t in tickers if t not in cached_tickers]
        if not tickers_to_download:
            print("Cache already contains all requested tickers. Skipping Stooq download.")
            return cached[cached["Ticker"].isin(tickers)].copy()
        print(f"Cache contains {len(cached_tickers)} tickers. Downloading {len(tickers_to_download)} missing tickers.")
    else:
        tickers_to_download = tickers

    frames = []
    failed = []

    for i, ticker in enumerate(tickers_to_download, start=1):
        print(f"Downloading {i}/{len(tickers_to_download)} from Stooq: {ticker}")
        panel = pd.DataFrame()

        for attempt in range(1, max_retries + 1):
            panel = _download_one_stooq_ticker(
                ticker=ticker,
                start=start,
                end=end,
                exchange_suffix=exchange_suffix,
            )
            if not panel.empty:
                break

            if attempt < max_retries:
                wait = sleep_seconds * attempt
                print(f"Retrying {ticker} after {wait:.1f} seconds...")
                time.sleep(wait)

        if panel.empty:
            failed.append(ticker)
        else:
            frames.append(panel)

        if i < len(tickers_to_download):
            time.sleep(sleep_seconds)

    downloaded = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    if cached.empty and downloaded.empty:
        raise RuntimeError(
            "No market data downloaded from Stooq. Check internet connection, ticker symbols, or Stooq availability."
        )

    combined = pd.concat([cached, downloaded], ignore_index=True) if not cached.empty else downloaded
    combined = combined.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    combined = combined.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    combined.to_csv(cache_file, index=False)
    print(f"Saved Stooq market data cache to {cache_file}")

    if failed:
        missing_path = os.path.splitext(cache_file)[0] + "_missing_tickers.json"
        with open(missing_path, "w", encoding="utf-8") as f:
            json.dump(failed, f, indent=2)
        print(f"Warning: {len(failed)} tickers had no Stooq data. Saved list to {missing_path}")

    return combined[combined["Ticker"].isin(tickers)].copy()


# Same technical indicators as the original script.
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
        raise RuntimeError("No ticker data available after download. Cannot build indicators.")

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


def train_latest_model(panel, feature_cols, train_days=TRAIN_DAYS, device="cuda"):
    dates = sorted(panel["Date"].unique())
    latest_prediction_date = dates[-1]

    trainable = panel.dropna(subset=feature_cols + ["Target"]).copy()
    trainable_dates = sorted(trainable["Date"].unique())

    if len(trainable_dates) < train_days:
        raise RuntimeError(
            f"Not enough trainable dates. Need {train_days}, found {len(trainable_dates)}. "
            "Try an earlier START date or fewer indicator windows."
        )

    train_dates = trainable_dates[-train_days:]
    train = trainable[trainable["Date"].isin(train_dates)].copy()

    X_train = train[feature_cols]
    y_train = train["Target"].astype(int)

    model = create_xgb_model(device=device)
    model.fit(X_train, y_train)

    train_pred = model.predict(X_train)
    acc = accuracy_score(y_train, train_pred)
    prec = precision_score(y_train, train_pred, zero_division=0)
    rec = recall_score(y_train, train_pred, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_train, train_pred, labels=[0, 1]).ravel()

    metrics = {
        "data_source": "stooq",
        "latest_prediction_date": str(pd.Timestamp(latest_prediction_date).date()),
        "train_start_date": str(pd.Timestamp(train_dates[0]).date()),
        "train_end_date": str(pd.Timestamp(train_dates[-1]).date()),
        "train_rows": int(len(train)),
        "train_positive_rate": float(y_train.mean()),
        "train_accuracy": float(acc),
        "train_precision": float(prec),
        "train_recall": float(rec),
        "train_TP": int(tp),
        "train_TN": int(tn),
        "train_FP": int(fp),
        "train_FN": int(fn),
    }

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

    model_path = os.path.join(model_dir, f"xgboost_model_stooq_{stamp}.joblib")
    picks_csv_path = os.path.join(output_dir, f"xgboost_buy_picks_stooq_{stamp}.csv")
    picks_json_path = os.path.join(output_dir, f"xgboost_buy_picks_stooq_{stamp}.json")
    metrics_path = os.path.join(output_dir, f"xgboost_train_metrics_stooq_{stamp}.json")
    feature_path = os.path.join(output_dir, f"xgboost_feature_columns_stooq_{stamp}.json")

    joblib.dump(model, model_path)
    picks.to_csv(picks_csv_path, index=False)

    picks_json = picks.copy()
    if not picks_json.empty:
        picks_json["Date"] = picks_json["Date"].astype(str)
    with open(picks_json_path, "w", encoding="utf-8") as f:
        json.dump(picks_json.to_dict(orient="records"), f, indent=2)

    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    with open(feature_path, "w", encoding="utf-8") as f:
        json.dump(feature_cols, f, indent=2)

    return {
        "model": model_path,
        "picks_csv": picks_csv_path,
        "picks_json": picks_json_path,
        "metrics": metrics_path,
        "feature_columns": feature_path,
    }


def main():
    parser = argparse.ArgumentParser(description="Train XGBoost on ticker universe using Stooq data and output current buy candidates.")
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE_FILE, help="Path to ticker_universe.json or plain ticker list JSON")
    parser.add_argument("--start", default=START, help="Start date for Stooq data")
    parser.add_argument("--end", default=END, help="End date for Stooq data; default is latest available")
    parser.add_argument("--train-days", type=int, default=TRAIN_DAYS)
    parser.add_argument("--threshold", type=float, default=PROBA_THRESHOLD)
    parser.add_argument("--max-positions", type=int, default=MAX_POSITIONS)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"], help="Use cuda if your XGBoost install/GPU supports it; otherwise use cpu")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--cache-file", default=DEFAULT_CACHE_FILE)
    parser.add_argument("--refresh-data", action="store_true", help="Ignore cached market data and redownload from Stooq")
    parser.add_argument("--sleep-seconds", type=float, default=1.5, help="Seconds to sleep between Stooq ticker requests")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per ticker")
    parser.add_argument("--exchange-suffix", default="us", help="Stooq exchange suffix. For US stocks, use 'us'.")
    args = parser.parse_args()

    print("XGBoost version:", xgb.__version__)
    print(f"Using XGBoost device: {args.device}")

    tickers = load_tickers_from_json(args.universe)
    print(f"Loaded {len(tickers)} tickers from {args.universe}")

    print("Downloading Stooq data...")
    prices = download_data(
        tickers,
        start=args.start,
        end=args.end,
        cache_file=args.cache_file,
        refresh=args.refresh_data,
        sleep_seconds=args.sleep_seconds,
        max_retries=args.max_retries,
        exchange_suffix=args.exchange_suffix,
    )

    available = sorted(prices["Ticker"].unique()) if not prices.empty else []
    print(f"Using {len(available)} tickers with Stooq data.")

    print("Building technical indicators and labels...")
    panel = add_indicators(prices)
    panel = panel.replace([np.inf, -np.inf], np.nan)

    feature_cols = make_features(panel)

    print("Training latest XGBoost model...")
    model, metrics, pred_date = train_latest_model(
        panel=panel,
        feature_cols=feature_cols,
        train_days=args.train_days,
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
