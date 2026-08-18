"""Broker boundary with deterministic fake execution and a disabled live skeleton."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from .ids import new_id
from .types import BrokerOrder, BrokerOrderRequest, Fill, OrderState


class BrokerAdapter(Protocol):
    name: str
    supports_live_execution: bool
    supports_fractional_shares: bool

    def submit_order(self, request: BrokerOrderRequest) -> tuple[BrokerOrder, tuple[Fill, ...]]: ...
    def orders(self) -> tuple[BrokerOrder, ...]: ...


@dataclass
class FakeBrokerAdapter:
    behavior: str = "full_fill"
    fill_price: Decimal = Decimal("100")
    name: str = "fake-broker"
    supports_live_execution: bool = False
    supports_fractional_shares: bool = False
    _orders: dict[str, BrokerOrder] = field(default_factory=dict)

    def submit_order(self, request: BrokerOrderRequest) -> tuple[BrokerOrder, tuple[Fill, ...]]:
        existing = next(
            (
                order
                for order in self._orders.values()
                if order.idempotency_key == request.idempotency_key
            ),
            None,
        )
        if existing:
            return existing, ()
        if self.behavior == "timeout":
            raise TimeoutError("Ambiguous simulated broker timeout")
        state = OrderState.REJECTED if self.behavior == "reject" else OrderState.FILLED
        filled = Decimal("0") if state == OrderState.REJECTED else request.quantity
        if self.behavior == "partial_fill":
            state, filled = OrderState.PARTIALLY_FILLED, request.quantity / Decimal("2")
        order = BrokerOrder(
            broker_order_id=new_id("broker_order"),
            client_order_id=request.client_order_id,
            idempotency_key=request.idempotency_key,
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
            filled_quantity=filled,
            state=state,
            status=state.value,
        )
        self._orders[order.broker_order_id] = order
        fills = (
            ()
            if filled == 0
            else (
                Fill(
                    fill_id=new_id("fill"),
                    broker_order_id=order.broker_order_id,
                    ticker=request.ticker,
                    side=request.side,
                    quantity=filled,
                    unit_price=request.limit_price or self.fill_price,
                    status="confirmed",
                ),
            )
        )
        return order, fills

    def orders(self) -> tuple[BrokerOrder, ...]:
        return tuple(self._orders.values())


class DisabledLiveBrokerAdapter:
    name = "disabled-live-adapter"
    supports_live_execution = False
    supports_fractional_shares = False

    def submit_order(self, request: BrokerOrderRequest) -> tuple[BrokerOrder, tuple[Fill, ...]]:
        raise PermissionError("Live broker submission is not implemented or enabled")

    def orders(self) -> tuple[BrokerOrder, ...]:
        return ()
