"""Immutable exact-order approval records."""

from datetime import timedelta

from .clock import utc_now
from .ids import new_id
from .security import sha256_json
from .types import OrderApproval, OrderIntent


def intent_hash(intent: OrderIntent) -> str:
    bound = {
        "order_intent_id": intent.order_intent_id,
        "ticker": intent.ticker,
        "side": intent.side,
        "quantity": str(intent.quantity),
        "order_type": intent.order_type,
        "limit_price": str(intent.limit_price) if intent.limit_price is not None else None,
        "maximum_notional": str(intent.maximum_notional),
        "model_id": intent.model_id,
        "recommendation_id": intent.recommendation_id,
        "risk_assessment_id": intent.risk_assessment_id,
        "environment": intent.environment,
    }
    return sha256_json(bound)


def approve(intent: OrderIntent, approved_by: str, minutes: int = 15) -> OrderApproval:
    return OrderApproval(
        approval_id=new_id("approval"),
        order_intent_id=intent.order_intent_id,
        intent_hash=intent_hash(intent),
        ticker=intent.ticker,
        side=intent.side,
        quantity=intent.quantity,
        order_type=intent.order_type,
        limit_price=intent.limit_price,
        maximum_notional=intent.maximum_notional,
        model_id=intent.model_id,
        recommendation_id=intent.recommendation_id,
        risk_assessment_id=intent.risk_assessment_id,
        environment=intent.environment,
        approved_by=approved_by,
        expires_at=utc_now() + timedelta(minutes=minutes),
        status="approved",
    )


def validate_approval(intent: OrderIntent, approval: OrderApproval) -> None:
    if approval.order_intent_id != intent.order_intent_id or approval.intent_hash != intent_hash(
        intent
    ):
        raise PermissionError("Approval does not bind to the exact order intent")
    if approval.environment != intent.environment:
        raise PermissionError("Approval environment differs from order intent")
    if approval.expires_at <= utc_now():
        raise PermissionError("Approval is expired")
