"""Only this service may submit approved intents to broker adapters."""

from .approvals import validate_approval
from .brokers import BrokerAdapter
from .config import Settings
from .ids import new_id
from .storage import Storage
from .types import (
    BrokerOrderRequest,
    ExecutionReport,
    OrderApproval,
    OrderIntent,
    RiskAssessment,
    RiskOutcome,
)


class ExecutionService:
    def __init__(self, settings: Settings, storage: Storage, broker: BrokerAdapter) -> None:
        self.settings = settings
        self.storage = storage
        self.broker = broker

    def live_gate_results(
        self,
        intent: OrderIntent,
        approval: OrderApproval,
        risk: RiskAssessment,
        market_data_fresh: bool,
        account_data_fresh: bool,
    ) -> dict[str, bool]:
        static = self.settings.live_static_gates()
        return {
            **static,
            "adapter_supports_live": self.broker.supports_live_execution,
            "deterministic_risk_approved": risk.outcome
            in {
                RiskOutcome.APPROVED,
                RiskOutcome.APPROVED_WITH_RESIZE,
                RiskOutcome.APPROVAL_REQUIRED,
            },
            "exact_human_approval": approval.approved_by not in {"paper-auto", "system"},
            "approval_not_expired_and_exact": self._approval_valid(intent, approval),
            "unique_idempotency_key_present": bool(intent.idempotency_key),
            "kill_switch_inactive": not self.storage.kill_switch_active(),
            "market_data_fresh": market_data_fresh,
            "account_state_fresh": account_data_fresh,
        }

    @staticmethod
    def _approval_valid(intent: OrderIntent, approval: OrderApproval) -> bool:
        try:
            validate_approval(intent, approval)
            return True
        except PermissionError:
            return False

    def execute(
        self,
        intent: OrderIntent,
        approval: OrderApproval,
        risk: RiskAssessment,
        *,
        market_data_fresh: bool = True,
        account_data_fresh: bool = True,
    ) -> ExecutionReport:
        validate_approval(intent, approval)
        if risk.risk_assessment_id != intent.risk_assessment_id:
            raise PermissionError("Risk assessment does not match order intent")
        if risk.outcome not in {
            RiskOutcome.APPROVED,
            RiskOutcome.APPROVED_WITH_RESIZE,
            RiskOutcome.APPROVAL_REQUIRED,
        }:
            raise PermissionError("Deterministic risk engine did not approve the intent")
        if self.storage.kill_switch_active():
            raise PermissionError("Emergency kill switch is active")
        if not market_data_fresh or not account_data_fresh:
            raise PermissionError("Market data or account state is stale")
        if self.settings.trading_mode == "live":
            gates = self.live_gate_results(
                intent, approval, risk, market_data_fresh, account_data_fresh
            )
            failed = [name for name, passed in gates.items() if not passed]
            if failed:
                raise PermissionError("Live execution gates failed: " + ", ".join(failed))
        elif self.broker.supports_live_execution:
            raise PermissionError("A live-capable adapter cannot be used in paper mode")
        if not self.storage.reserve_idempotency_key(intent.idempotency_key, intent.order_intent_id):
            raise PermissionError("Duplicate order idempotency key")
        request = BrokerOrderRequest(
            client_order_id=new_id("client_order"),
            idempotency_key=intent.idempotency_key,
            ticker=intent.ticker,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
        )
        self.storage.save(
            "order_intent", intent.order_intent_id, intent.run_id, "submission_pending", intent
        )
        try:
            order, fills = self.broker.submit_order(request)
        except TimeoutError:
            self.storage.save(
                "order_intent",
                intent.order_intent_id,
                intent.run_id,
                "reconciliation_required",
                intent,
            )
            raise
        report = ExecutionReport(
            order_intent_id=intent.order_intent_id,
            broker_order=order,
            fills=fills,
            run_id=intent.run_id,
            correlation_id=intent.correlation_id,
            causation_id=intent.id,
            status=order.state.value,
        )
        self.storage.save(
            "broker_order", order.broker_order_id, intent.run_id, order.state.value, order
        )
        for fill in fills:
            self.storage.save("fill", fill.fill_id, intent.run_id, "confirmed", fill)
        return report
