import argparse
import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf


def load_tickers(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if "tickers" in data:
        items = data["tickers"]
        if items and isinstance(items[0], dict):
            return [x["ticker"] for x in items]
        return items

    raise ValueError("Could not find tickers in universe JSON")


def download_one(ticker, start):
    df = yf.download(
        ticker,
        start=start,
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if df.empty:
        return None

    # Fix yfinance MultiIndex columns like ('Open', 'NVDA')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df["Ticker"] = ticker.upper()

    return df[["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="ticker_universe.json")
    parser.add_argument("--output", default="data/raw/market_data.parquet")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--sleep", type=float, default=2.0)
    args = parser.parse_args()

    tickers = load_tickers(args.universe)
    print(f"Loaded {len(tickers)} tickers")

    frames = []

    for i, ticker in enumerate(tickers, 1):
        print(f"{i}/{len(tickers)} downloading {ticker}")

        try:
            df = download_one(ticker, args.start)
            if df is not None:
                frames.append(df)
            else:
                print(f"No data for {ticker}")
        except Exception as e:
            print(f"Failed {ticker}: {e}")

        time.sleep(args.sleep)

    if not frames:
        raise RuntimeError("No market data downloaded")

    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"])

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    out.to_parquet(output, index=False)
    print(f"Saved {len(out):,} rows to {output}")


if __name__ == "__main__":
    main()
