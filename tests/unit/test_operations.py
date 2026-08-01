import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from trading_system.audit import Alert, JsonFormatter, TestAlertSink
from trading_system.backtesting import BacktestConfig, run_backtest
from trading_system.config import Settings
from trading_system.market_data import FakeMarketDataProvider, MarketBar, validate_bars
from trading_system.observability import Metrics, health
from trading_system.storage import Storage


def test_market_quality_provider_and_impossible_bar() -> None:
    now = datetime.now(UTC)
    valid = MarketBar(
        ticker="TEST",
        session=now,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        provider="fixture",
    )
    invalid = valid.model_copy(update={"high": Decimal("8"), "session": now.replace(day=2)})
    provider = FakeMarketDataProvider((valid, invalid))
    report = validate_bars(provider.bars(("TEST",)))
    assert report.status == "invalid"
    assert any(item.startswith("impossible_high_low") for item in report.quality_warnings)


def test_structured_redacted_logging_alert_dedup_metrics_and_health(tmp_path) -> None:
    record = logging.LogRecord("test", logging.INFO, "", 0, "Bearer abc", (), None)
    record.event_name = "test_event"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "Bearer [REDACTED]"
    sink = TestAlertSink()
    sink.emit(Alert("one", "warning", "first"))
    sink.emit(Alert("one", "warning", "duplicate"))
    assert len(sink.alerts) == 1
    metrics = Metrics()
    metrics.increment("run_count")
    assert "trading_system_run_count 1.0" in metrics.prometheus()
    storage = Storage(tmp_path / "health.db")
    report = health(Settings(), storage)
    assert report["live_trading_readiness"] is False
    storage.close()


def test_backtest_uses_next_session_and_costs() -> None:
    dates = pd.bdate_range("2025-01-01", periods=8)
    prices = pd.DataFrame(
        {
            "Date": dates,
            "Ticker": ["TEST"] * len(dates),
            "Open": [10, 11, 12, 13, 14, 15, 16, 17],
            "Close": [10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5],
            "Volume": [1_000_000] * len(dates),
        }
    )
    signals = pd.DataFrame({"Date": [dates[0]], "Ticker": ["TEST"], "Score": [0.9]})
    report = run_backtest(
        signals,
        prices,
        BacktestConfig(max_positions=1, holding_sessions=2, commission_per_trade=1),
    )
    assert report.trade_count == 1
    assert report.total_return > 0
    assert "next-session open plus slippage" in report.assumptions[1]
