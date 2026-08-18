"""The single Yahoo Finance boundary used by research, models, and simulation."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import pandas as pd

from .security import sha256_json
from .types import MarketBar, MarketDataSnapshot


class MarketDataError(RuntimeError):
    """Yahoo returned no usable data after retrying."""


class MarketDataProvider(Protocol):
    name: str

    def history(
        self, tickers: Iterable[str], *, start: date | str, end: date | str | None = None
    ) -> pd.DataFrame: ...

    def latest(self, tickers: Iterable[str]) -> dict[str, LatestPrice]: ...


@dataclass(frozen=True)
class LatestPrice:
    ticker: str
    price: Decimal | None
    session: date | None
    retrieved_at: datetime
    stale: bool
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class FakeMarketDataProvider:
    frame: pd.DataFrame
    name: str = "fixture"

    def history(
        self, tickers: Iterable[str], *, start: date | str, end: date | str | None = None
    ) -> pd.DataFrame:
        allowed = {ticker.upper() for ticker in tickers}
        result = self.frame[self.frame["Ticker"].str.upper().isin(allowed)].copy()
        result = result[pd.to_datetime(result["Date"]).dt.date >= pd.Timestamp(start).date()]
        if end is not None:
            result = result[pd.to_datetime(result["Date"]).dt.date < pd.Timestamp(end).date()]
        return result.reset_index(drop=True)

    def latest(self, tickers: Iterable[str]) -> dict[str, LatestPrice]:
        now = datetime.now(UTC)
        result: dict[str, LatestPrice] = {}
        frame = self.history(tickers, start="1900-01-01")
        for ticker in {item.upper() for item in tickers}:
            rows = frame[frame["Ticker"].str.upper() == ticker].sort_values("Date")
            if rows.empty:
                result[ticker] = LatestPrice(ticker, None, None, now, True, False, "unavailable")
            else:
                row = rows.iloc[-1]
                session = pd.Timestamp(row["Date"]).date()
                result[ticker] = LatestPrice(
                    ticker, Decimal(str(row["Close"])), session, now, False, True
                )
        return result

    def completed_session(self, benchmark: str = "SPY") -> date | None:
        return self.latest((benchmark,))[benchmark].session


class YahooFinanceMarketDataService:
    """Batched, normalized, retrying Yahoo daily-bar service.

    `downloader` is injectable so tests never contact Yahoo. The service never
    suppresses a failed batch: unavailable symbols are returned explicitly and
    a completely failed request raises `MarketDataError`.
    """

    name = "yahoo-finance"

    def __init__(
        self,
        *,
        cache_dir: Path = Path("data/cache/yahoo"),
        batch_size: int = 50,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        rate_limit_seconds: float = 0.25,
        downloader: Callable[..., pd.DataFrame] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.rate_limit_seconds = rate_limit_seconds
        self._downloader = downloader
        self._sleep = sleep

    @property
    def downloader(self) -> Callable[..., pd.DataFrame]:
        if self._downloader is None:
            import yfinance as yf

            self._downloader = yf.download
        return self._downloader

    @staticmethod
    def _tickers(values: Iterable[str]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip().upper() for item in values if item.strip()))
        if not normalized:
            raise ValueError("At least one ticker is required")
        return normalized

    def history(
        self, tickers: Iterable[str], *, start: date | str, end: date | str | None = None
    ) -> pd.DataFrame:
        symbols = self._tickers(tickers)
        frames: list[pd.DataFrame] = []
        failures: list[str] = []
        for offset in range(0, len(symbols), self.batch_size):
            batch = symbols[offset : offset + self.batch_size]
            try:
                raw = self._retry_download(batch, start=start, end=end)
                normalized = self.normalize(raw, batch)
                if not normalized.empty:
                    frames.append(normalized)
                missing = set(batch) - set(normalized["Ticker"].unique())
                failures.extend(sorted(missing))
            except Exception as exc:
                failures.extend(batch)
                if len(symbols) == len(batch):
                    raise MarketDataError(
                        f"Yahoo download failed for {','.join(batch)}: {exc}"
                    ) from exc
            if offset + self.batch_size < len(symbols):
                self._sleep(self.rate_limit_seconds)
        if not frames:
            raise MarketDataError("Yahoo returned no usable market data")
        result = pd.concat(frames, ignore_index=True).drop_duplicates(["Date", "Ticker"])
        result.attrs["unavailable_tickers"] = tuple(sorted(set(failures)))
        return result.sort_values(["Ticker", "Date"]).reset_index(drop=True)

    def _retry_download(
        self, batch: tuple[str, ...], *, start: date | str, end: date | str | None
    ) -> pd.DataFrame:
        error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                frame = self.downloader(
                    list(batch),
                    start=str(start),
                    end=str(end) if end else None,
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                    group_by="column",
                )
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    return frame
                error = ValueError("empty response")
            except Exception as exc:
                error = exc
            if attempt + 1 < self.max_retries:
                self._sleep(self.backoff_seconds * (2**attempt))
        raise MarketDataError(str(error or "unknown Yahoo error"))

    @staticmethod
    def normalize(frame: pd.DataFrame, requested: Iterable[str]) -> pd.DataFrame:
        """Normalize every common yfinance single/multi-symbol column shape."""
        symbols = tuple(item.upper() for item in requested)
        columns = ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]
        if frame.empty:
            return pd.DataFrame(columns=columns)
        pieces: list[pd.DataFrame] = []
        if isinstance(frame.columns, pd.MultiIndex):
            level0 = {str(value) for value in frame.columns.get_level_values(0)}
            price_first = bool({"Open", "Close", "Adj Close"} & level0)
            for symbol in symbols:
                try:
                    part = frame.xs(symbol, axis=1, level=1 if price_first else 0).copy()
                except KeyError:
                    continue
                pieces.append(YahooFinanceMarketDataService._normalize_one(part, symbol))
        else:
            symbol = symbols[0] if len(symbols) == 1 else ""
            if symbol:
                pieces.append(YahooFinanceMarketDataService._normalize_one(frame.copy(), symbol))
        if not pieces:
            return pd.DataFrame(columns=columns)
        result = pd.concat(pieces, ignore_index=True)
        for name in ["Open", "High", "Low", "Close", "Volume"]:
            result[name] = pd.to_numeric(result[name], errors="coerce")
        return result.dropna(subset=["Date", "Ticker", "Open", "High", "Low", "Close"])[columns]

    @staticmethod
    def _normalize_one(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if "Close" not in frame and "Adj Close" in frame:
            frame["Close"] = frame["Adj Close"]
        if "Volume" not in frame:
            frame["Volume"] = 0
        frame = frame.reset_index()
        date_column = "Date" if "Date" in frame else frame.columns[0]
        frame = frame.rename(columns={date_column: "Date"})
        frame["Date"] = pd.to_datetime(frame["Date"], utc=True).dt.tz_convert(None)
        frame["Ticker"] = symbol
        return frame

    def latest(self, tickers: Iterable[str]) -> dict[str, LatestPrice]:
        symbols = self._tickers(tickers)
        today = datetime.now(UTC).date()
        frame = self.history(
            symbols, start=today - timedelta(days=14), end=today + timedelta(days=1)
        )
        retrieved = datetime.now(UTC)
        output: dict[str, LatestPrice] = {}
        for symbol in symbols:
            rows = frame[frame["Ticker"] == symbol].sort_values("Date")
            if rows.empty:
                output[symbol] = LatestPrice(
                    symbol, None, None, retrieved, True, False, "unavailable"
                )
                continue
            row = rows.iloc[-1]
            session = pd.Timestamp(row["Date"]).date()
            age = (today - session).days
            output[symbol] = LatestPrice(
                symbol,
                Decimal(str(row["Close"])),
                session,
                retrieved,
                age > 4,
                True,
                "stale" if age > 4 else None,
            )
        return output

    def validate_symbols(self, tickers: Iterable[str]) -> dict[str, LatestPrice]:
        return self.latest(tickers)

    def completed_session(self, benchmark: str = "SPY") -> date | None:
        point = self.latest((benchmark,))[benchmark]
        return point.session if point.available and not point.stale else None

    def update_cache(self, tickers: Iterable[str], *, start: date | str = "2015-01-01") -> Path:
        frame = self.history(tickers, start=start)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        destination = self.cache_dir / "daily_ohlcv.parquet"
        if destination.exists():
            previous = pd.read_parquet(destination)
            frame = pd.concat([previous, frame], ignore_index=True)
            frame = frame.drop_duplicates(["Date", "Ticker"], keep="last")
        temporary = destination.with_suffix(".parquet.tmp")
        frame.sort_values(["Ticker", "Date"]).to_parquet(temporary, index=False)
        temporary.replace(destination)
        return destination


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


def dataframe_to_bars(
    frame: pd.DataFrame, provider: str = "yahoo-finance"
) -> tuple[MarketBar, ...]:
    required = {"Date", "Ticker", "Open", "High", "Low", "Close", "Volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing market-data columns: {sorted(missing)}")
    bars: list[MarketBar] = []
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
