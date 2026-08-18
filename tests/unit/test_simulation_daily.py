from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from trading_system.config import Settings
from trading_system.daily import DailyMarketCycle
from trading_system.market_data import FakeMarketDataProvider
from trading_system.signals import FixedSignalService
from trading_system.simulation import SimulatedExecutionEngine, StopLossPolicy
from trading_system.storage import Storage


def test_buy_sell_pnl_and_execution_idempotency(tmp_path) -> None:
    storage = Storage(tmp_path / "state.db")
    engine = SimulatedExecutionEngine(storage, Decimal("10000"))
    buy = engine.execute(
        strategy_run_id="run1",
        universe_run_id="u1",
        market_session=date(2026, 8, 14),
        ticker="AAA",
        side="BUY",
        quantity=Decimal("10"),
        price=Decimal("100"),
        decision_type="MODEL_ENTRY",
        reason="model",
    )
    replay = engine.execute(
        strategy_run_id="run1",
        universe_run_id="u1",
        market_session=date(2026, 8, 14),
        ticker="AAA",
        side="BUY",
        quantity=Decimal("10"),
        price=Decimal("100"),
        decision_type="MODEL_ENTRY",
        reason="model",
    )
    assert replay.execution_id == buy.execution_id
    sell = engine.execute(
        strategy_run_id="run2",
        universe_run_id="u1",
        market_session=date(2026, 8, 17),
        ticker="AAA",
        side="SELL",
        quantity=Decimal("4"),
        price=Decimal("110"),
        decision_type="SIGNAL_EXIT",
        reason="signal",
    )
    assert sell.realized_pnl == Decimal("40.00")
    assert engine.state()[0] == Decimal("9440")
    assert engine.positions()["AAA"][0] == Decimal("6")
    with pytest.raises(ValueError, match="more"):
        engine.execute(
            strategy_run_id="run3",
            universe_run_id="u1",
            market_session=date(2026, 8, 18),
            ticker="AAA",
            side="SELL",
            quantity=Decimal("99"),
            price=Decimal("110"),
            decision_type="MANUAL_EXIT",
            reason="test",
        )


def test_stop_loss_and_authoritative_snapshot(tmp_path) -> None:
    storage = Storage(tmp_path / "state.db")
    engine = SimulatedExecutionEngine(storage, Decimal("1000"))
    engine.execute(
        strategy_run_id="r",
        universe_run_id="u",
        market_session=date(2026, 8, 14),
        ticker="AAA",
        side="BUY",
        quantity=Decimal("5"),
        price=Decimal("100"),
        decision_type="MODEL_ENTRY",
        reason="model",
    )
    policy = StopLossPolicy(Decimal("0.08"))
    assert policy.stop_price(Decimal("100")) == Decimal("92.00")
    assert policy.breached(Decimal("100"), Decimal("91"))
    first = engine.snapshot(
        strategy_run_id="r", market_session=date(2026, 8, 14), prices={"AAA": Decimal("105")}
    )
    second = engine.snapshot(
        strategy_run_id="other", market_session=date(2026, 8, 14), prices={"AAA": Decimal("1")}
    )
    assert first["id"] == second["id"]


def seeded_storage(path):
    storage = Storage(path)
    now = datetime.now(UTC).isoformat()
    storage.execute(
        "INSERT INTO universe_runs VALUES "
        "('u1','2026-08','default',?,'fixture','model','v1','completed',NULL)",
        (now,),
    )
    with storage.transaction() as db:
        for rank in range(1, 101):
            ticker = f"T{rank:03d}"
            db.execute(
                "INSERT INTO universe_members VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "u1",
                    ticker,
                    ticker,
                    rank,
                    "Tech",
                    "Infra",
                    "reason",
                    "thesis",
                    "[]",
                    "[]",
                    "0.8",
                    now,
                ),
            )
    return storage


def daily_frame():
    tickers = [f"T{i:03d}" for i in range(1, 101)] + ["SPY", "QQQ"]
    rows = []
    for ticker in tickers:
        for day, price in [("2026-08-14", 99), ("2026-08-17", 100)]:
            rows.append(
                {
                    "Date": pd.Timestamp(day),
                    "Ticker": ticker,
                    "Open": price,
                    "High": price + 1,
                    "Low": price - 1,
                    "Close": price,
                    "Volume": 100000,
                }
            )
    return pd.DataFrame(rows)


def test_daily_cycle_market_awareness_and_idempotency(tmp_path) -> None:
    storage = seeded_storage(tmp_path / "state.db")
    settings = Settings(
        database_path=tmp_path / "state.db",
        artifact_root=tmp_path / "artifacts",
        initial_capital=Decimal("10000"),
        risk={
            "minimum_cash_reserve": "1000",
            "maximum_position_notional": "2000",
            "maximum_position_percent": "0.25",
        },
    )
    cycle = DailyMarketCycle(
        settings=settings,
        storage=storage,
        market_data=FakeMarketDataProvider(daily_frame()),
        signals=FixedSignalService({"T001": Decimal("0.8"), "T002": Decimal("0.7")}),
    )
    result = cycle.run()
    assert result["status"] == "completed"
    assert storage.row("SELECT COUNT(*) count FROM portfolio_snapshots")["count"] == 1
    replay = cycle.run()
    assert replay["status"] == "skipped"
    assert storage.row("SELECT COUNT(*) count FROM simulated_trades")["count"] == 2
