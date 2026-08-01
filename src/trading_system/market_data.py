"""Market-data provider boundaries and deterministic quality validation."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import pandas as pd

from .security import sha256_json
from .types import MarketBar, MarketDataSnapshot


class MarketDataProvider(Protocol):
    name: str

    def bars(self, tickers: tuple[str, ...]) -> tuple[MarketBar, ...]: ...


@dataclass(frozen=True)
class FakeMarketDataProvider:
    fixture_bars: tuple[MarketBar, ...]
    name: str = "fixture"

    def bars(self, tickers: tuple[str, ...]) -> tuple[MarketBar, ...]:
        allowed = set(tickers)
        return tuple(bar for bar in self.fixture_bars if bar.ticker in allowed)


@dataclass(frozen=True)
class LocalParquetMarketDataProvider:
    """Read-only adapter for parquet files produced by the preserved downloader."""

    path: Path
    name: str = "local-parquet"

    def bars(self, tickers: tuple[str, ...]) -> tuple[MarketBar, ...]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        frame = pd.read_parquet(self.path)
        selected = frame[frame["Ticker"].astype(str).str.upper().isin(set(tickers))]
        return dataframe_to_bars(selected, self.name)


def validate_bars(bars: tuple[MarketBar, ...]) -> MarketDataSnapshot:
    warnings: list[str] = []
    seen: set[tuple[str, datetime]] = set()
    for bar in bars:
        key = (bar.ticker, bar.session)
        if key in seen:
            warnings.append(f"duplicate_bar:{bar.ticker}:{bar.session.isoformat()}")
        seen.add(key)
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            warnings.append(f"non_positive_price:{bar.ticker}:{bar.session.date()}")
        if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(
            bar.open, bar.close, bar.high
        ):
            warnings.append(f"impossible_high_low:{bar.ticker}:{bar.session.date()}")
        if bar.volume < 0:
            warnings.append(f"negative_volume:{bar.ticker}:{bar.session.date()}")
    content = [
        bar.model_dump(mode="json") for bar in sorted(bars, key=lambda b: (b.ticker, b.session))
    ]
    return MarketDataSnapshot(
        bars=bars,
        content_hash=sha256_json(content),
        quality_warnings=tuple(sorted(set(warnings))),
        status="valid" if not warnings else "invalid",
        data_as_of=max((bar.session for bar in bars), default=datetime.now(UTC)),
    )


def dataframe_to_bars(frame: pd.DataFrame, provider: str = "local_file") -> tuple[MarketBar, ...]:
    required = {"Date", "Ticker", "Open", "High", "Low", "Close", "Volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing market-data columns: {sorted(missing)}")
    bars = []
    for row in frame[list(required)].to_dict(orient="records"):
        session = pd.Timestamp(row["Date"])
        if session.tzinfo is None:
            session = session.tz_localize("UTC")
        bars.append(
            MarketBar(
                ticker=str(row["Ticker"]).upper(),
                session=session.to_pydatetime(),
                open=Decimal(str(row["Open"])),
                high=Decimal(str(row["High"])),
                low=Decimal(str(row["Low"])),
                close=Decimal(str(row["Close"])),
                volume=Decimal(str(row["Volume"])),
                provider=provider,
            )
        )
    return tuple(bars)
