from datetime import timedelta
from decimal import Decimal

import pytest

from trading_system.approvals import approve
from trading_system.brokers import DisabledLiveBrokerAdapter, FakeBrokerAdapter
from trading_system.clock import utc_now
from trading_system.config import Settings
from trading_system.execution import ExecutionService
from trading_system.risk import RiskEngine, size_fixed_notional
from trading_system.storage import Storage
from trading_system.types import (
    PortfolioSnapshot,
    RecommendationAction,
    TradeRecommendation,
)


def recommendation() -> TradeRecommendation:
    return TradeRecommendation(
        recommendation_id="recommendation-1",
        ticker="TEST",
        action=RecommendationAction.BUY,
        rationale="fixture",
        model_signal_id="signal-1",
        provisional_notional=Decimal("1000"),
        confidence=Decimal("0.8"),
        expected_horizon="50 sessions",
        expires_at=utc_now() + timedelta(hours=1),
    )


def approved_context(storage: Storage):
    rec = recommendation()
    portfolio = PortfolioSnapshot(cash=Decimal("100000"))
    quantity = size_fixed_notional(rec, Decimal("100"), portfolio.cash)
    risk, intent = RiskEngine(Settings().risk, storage).evaluate(
        rec, portfolio, quantity, Decimal("100"), "model-1", sector="technology"
    )
    assert intent is not None
    return risk, intent, approve(intent, "paper-auto")


def test_paper_execution_idempotency_reconciliation_boundary(tmp_path) -> None:
    storage = Storage(tmp_path / "state.db")
    risk, intent, approval = approved_context(storage)
    broker = FakeBrokerAdapter(fill_price=Decimal("100"))
    report = ExecutionService(Settings(), storage, broker).execute(intent, approval, risk)
    assert report.broker_order.state == "filled"
    assert len(report.fills) == 1
    with pytest.raises(PermissionError, match="Duplicate"):
        ExecutionService(Settings(), storage, broker).execute(intent, approval, risk)


def test_kill_switch_stale_data_expired_approval_and_ambiguous_timeout_fail_closed(
    tmp_path,
) -> None:
    storage = Storage(tmp_path / "state.db")
    risk, intent, approval = approved_context(storage)
    service = ExecutionService(Settings(), storage, FakeBrokerAdapter())
    storage.set_kill_switch(True, "test")
    with pytest.raises(PermissionError, match="kill switch"):
        service.execute(intent, approval, risk)
    storage.set_kill_switch(False, "test complete")
    with pytest.raises(PermissionError, match="stale"):
        service.execute(intent, approval, risk, market_data_fresh=False)
    expired = approval.model_copy(update={"expires_at": utc_now() - timedelta(seconds=1)})
    with pytest.raises(PermissionError, match="expired"):
        service.execute(intent, expired, risk)
    timeout_service = ExecutionService(Settings(), storage, FakeBrokerAdapter(behavior="timeout"))
    with pytest.raises(TimeoutError):
        timeout_service.execute(intent, approval, risk)
    assert storage.load("order_intent", intent.order_intent_id)["status"] == "awaiting_approval"


def test_live_mode_requires_every_gate_and_adapter_remains_disabled(tmp_path) -> None:
    storage = Storage(tmp_path / "state.db")
    risk, intent, _ = approved_context(storage)
    intent = intent.model_copy(update={"environment": "live"})
    human = approve(intent, "human@example.invalid")
    settings = Settings(
        trading_mode="live",
        paper_auto_approve=False,
        enable_live_trading=True,
        live_adapter_enabled=True,
        live_execution_tests_passed=True,
        live_warning_acknowledged=True,
        broker_credentials_present=True,
    )
    service = ExecutionService(settings, storage, DisabledLiveBrokerAdapter())
    gates = service.live_gate_results(intent, human, risk, True, True)
    assert gates["adapter_supports_live"] is False
    with pytest.raises(PermissionError, match="adapter_supports_live"):
        service.execute(intent, human, risk)
