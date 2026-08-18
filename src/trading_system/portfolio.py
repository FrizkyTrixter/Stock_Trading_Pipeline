"""Immutable paper portfolio ledger events and deterministic snapshots."""

from dataclasses import dataclass
from decimal import Decimal

from .clock import utc_now
from .ids import new_id
from .types import Fill, PortfolioSnapshot, PositionSnapshot


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    event_type: str
    effective_at: str
    ticker: str
    quantity: Decimal
    amount: Decimal
    fee: Decimal
    source_id: str


class PortfolioLedger:
    def __init__(self, opening_cash: Decimal) -> None:
        self.opening_cash = opening_cash
        self.events: list[LedgerEvent] = []

    def apply_fill(self, fill: Fill) -> LedgerEvent:
        signed_quantity = fill.quantity if fill.side == "buy" else -fill.quantity
        cash_amount = (
            -(fill.quantity * fill.unit_price + fill.fee)
            if fill.side == "buy"
            else fill.quantity * fill.unit_price - fill.fee
        )
        event = LedgerEvent(
            event_id=new_id("ledger"),
            event_type="fill",
            effective_at=utc_now().isoformat(),
            ticker=fill.ticker,
            quantity=signed_quantity,
            amount=cash_amount,
            fee=fill.fee,
            source_id=fill.fill_id,
        )
        if any(existing.source_id == event.source_id for existing in self.events):
            raise ValueError("Duplicate fill ledger event")
        self.events.append(event)
        return event

    def snapshot(
        self, prices: dict[str, Decimal], sectors: dict[str, str] | None = None
    ) -> PortfolioSnapshot:
        sectors = sectors or {}
        cash = self.opening_cash + sum(event.amount for event in self.events)
        quantities: dict[str, Decimal] = {}
        costs: dict[str, Decimal] = {}
        for event in self.events:
            quantities[event.ticker] = quantities.get(event.ticker, Decimal("0")) + event.quantity
            if event.quantity > 0:
                costs[event.ticker] = costs.get(event.ticker, Decimal("0")) - event.amount
        positions = tuple(
            PositionSnapshot(
                ticker=ticker,
                quantity=quantity,
                average_cost=(costs.get(ticker, Decimal("0")) / quantity)
                if quantity
                else Decimal("0"),
                market_price=prices[ticker],
                sector=sectors.get(ticker, "unknown"),
            )
            for ticker, quantity in sorted(quantities.items())
            if quantity != 0
        )
        return PortfolioSnapshot(cash=cash, positions=positions, status="current")
