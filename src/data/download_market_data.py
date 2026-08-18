"""Backward-compatible wrapper around the centralized Yahoo service."""

import argparse
import json
from pathlib import Path

from trading_system.market_data import YahooFinanceMarketDataService


def load_tickers(path: Path) -> tuple[str, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    values = data if isinstance(data, list) else data["tickers"]
    return tuple((item["ticker"] if isinstance(item, dict) else item).upper() for item in values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2015-01-01")
    args = parser.parse_args()
    frame = YahooFinanceMarketDataService(cache_dir=args.output.parent).history(
        load_tickers(args.universe), start=args.start
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    print(f"Saved {len(frame):,} normalized rows to {args.output}")


if __name__ == "__main__":
    main()
