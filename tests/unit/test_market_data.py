from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from trading_system.market_data import MarketDataError, YahooFinanceMarketDataService


def multi_frame() -> pd.DataFrame:
    index = pd.to_datetime(["2026-08-14", "2026-08-17"])
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], ["AAA", "BBB"]]
    )
    values = [
        [10, 20, 11, 21, 9, 19, 10.5, 20.5, 1000, 2000],
        [11, 21, 12, 22, 10, 20, 11.5, 21.5, 1100, 2100],
    ]
    return pd.DataFrame(values, index=index, columns=columns)


def test_normalizes_batched_multiindex_and_latest() -> None:
    calls = []

    def download(tickers, **kwargs):
        calls.append((tickers, kwargs))
        return multi_frame()

    service = YahooFinanceMarketDataService(downloader=download, sleep=lambda _: None)
    frame = service.history(("aaa", "bbb"), start=date(2026, 8, 1))
    assert list(frame.columns) == ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]
    assert set(frame["Ticker"]) == {"AAA", "BBB"}
    latest = service.latest(("AAA", "BBB"))
    assert latest["AAA"].price == Decimal("11.5")
    assert len(calls) == 2


def test_retries_transient_error_and_surfaces_total_failure() -> None:
    attempts = 0

    def flaky(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary")
        return multi_frame().xs("AAA", axis=1, level=1)

    service = YahooFinanceMarketDataService(downloader=flaky, max_retries=3, sleep=lambda _: None)
    assert not service.history(("AAA",), start="2026-01-01").empty
    assert attempts == 3
    broken = YahooFinanceMarketDataService(
        downloader=lambda *a, **k: pd.DataFrame(), max_retries=2, sleep=lambda _: None
    )
    with pytest.raises(MarketDataError, match="failed"):
        broken.history(("BAD",), start="2026-01-01")


def test_missing_ticker_is_explicit() -> None:
    service = YahooFinanceMarketDataService(
        downloader=lambda *a, **k: multi_frame().xs("AAA", axis=1, level=1), sleep=lambda _: None
    )
    frame = service.history(("AAA",), start="2026-01-01")
    assert frame.attrs["unavailable_tickers"] == ()
