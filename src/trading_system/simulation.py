"""Decimal-safe portfolio accounting and Yahoo-priced simulated execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal

from .ids import new_id
from .storage import Storage


@dataclass(frozen=True)
class SimulatedTrade:
    execution_id: str
    decision_id: str
    ticker: str
    side: str
    quantity: Decimal
    price: Decimal
    notional: Decimal
    fees: Decimal
    realized_pnl: Decimal


class StopLossPolicy:
    def __init__(self, percent: Decimal) -> None:
        if percent <= 0 or percent >= 1:
            raise ValueError("stop loss percent must be between zero and one")
        self.percent = percent

    def stop_price(self, average_cost: Decimal) -> Decimal:
        return (average_cost * (Decimal("1") - self.percent)).quantize(Decimal("0.01"))

    def breached(self, average_cost: Decimal, current_price: Decimal) -> bool:
        return current_price <= self.stop_price(average_cost)


class SimulatedExecutionEngine:
    """The only execution layer. It has no network or real-broker capability."""

    def __init__(
        self, storage: Storage, initial_capital: Decimal, fee: Decimal = Decimal("0")
    ) -> None:
        self.storage = storage
        self.fee = fee
        storage.initialize_portfolio(str(initial_capital))

    def state(self) -> tuple[Decimal, Decimal, Decimal]:
        row = self.storage.row("SELECT * FROM portfolio_state WHERE singleton=1")
        if row is None:
            raise RuntimeError("portfolio not initialized")
        return Decimal(row["cash"]), Decimal(row["starting_capital"]), Decimal(row["realized_pnl"])

    def positions(self) -> dict[str, tuple[Decimal, Decimal]]:
        return {
            row["ticker"]: (Decimal(row["quantity"]), Decimal(row["average_cost"]))
            for row in self.storage.rows("SELECT * FROM positions")
        }

    def execute(
        self,
        *,
        strategy_run_id: str,
        universe_run_id: str,
        market_session: date,
        ticker: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        decision_type: str,
        reason: str,
        metadata: dict[str, str] | None = None,
    ) -> SimulatedTrade:
        side = side.upper()
        ticker = ticker.upper()
        if side not in {"BUY", "SELL"} or quantity <= 0 or price <= 0:
            raise ValueError("invalid simulated transaction")
        quantity = quantity.quantize(Decimal("1"), rounding=ROUND_DOWN)
        if quantity <= 0:
            raise ValueError("quantity rounds to zero")
        key = f"{strategy_run_id}:{market_session}:{ticker}:{decision_type}"
        existing = self.storage.row(
            "SELECT id FROM trade_decisions WHERE idempotency_key=?", (key,)
        )
        if existing:
            row = self.storage.row(
                "SELECT * FROM simulated_trades WHERE decision_id=?", (existing["id"],)
            )
            if row is None:
                raise RuntimeError("decision exists without execution")
            return SimulatedTrade(
                row["id"],
                row["decision_id"],
                row["ticker"],
                row["side"],
                Decimal(row["quantity"]),
                Decimal(row["price"]),
                Decimal(row["notional"]),
                Decimal(row["fees"]),
                Decimal(row["realized_pnl"]),
            )
        now = datetime.now(UTC).isoformat()
        decision_id = new_id("decision")
        execution_id = new_id("execution")
        notional = (quantity * price).quantize(Decimal("0.01"))
        cash, starting, realized_total = self.state()
        positions = self.positions()
        old_quantity, old_cost = positions.get(ticker, (Decimal("0"), Decimal("0")))
        prices = {symbol: cost for symbol, (_, cost) in positions.items()}
        prices[ticker] = price
        value_before = cash + sum(qty * prices[symbol] for symbol, (qty, _) in positions.items())
        realized = Decimal("0")
        if side == "BUY":
            debit = notional + self.fee
            if debit > cash:
                raise ValueError("insufficient simulated cash")
            new_quantity = old_quantity + quantity
            new_cost = ((old_quantity * old_cost) + notional + self.fee) / new_quantity
            new_cash = cash - debit
        else:
            if quantity > old_quantity:
                raise ValueError("cannot sell more than the simulated holding")
            realized = ((price - old_cost) * quantity - self.fee).quantize(Decimal("0.01"))
            new_quantity = old_quantity - quantity
            new_cost = old_cost
            new_cash = cash + notional - self.fee
        value_after = value_before - self.fee
        with self.storage.transaction() as db:
            db.execute(
                "INSERT INTO trade_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    strategy_run_id,
                    universe_run_id,
                    market_session.isoformat(),
                    ticker,
                    decision_type,
                    reason,
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    key,
                ),
            )
            if new_quantity == 0:
                db.execute("DELETE FROM positions WHERE ticker=?", (ticker,))
            else:
                db.execute(
                    "INSERT INTO positions VALUES (?, ?, ?, ?, ?) ON CONFLICT(ticker) DO UPDATE "
                    "SET quantity=excluded.quantity, average_cost=excluded.average_cost, "
                    "updated_at=excluded.updated_at",
                    (ticker, str(new_quantity), str(new_cost), now, now),
                )
            db.execute(
                "UPDATE portfolio_state SET cash=?, realized_pnl=?, updated_at=? WHERE singleton=1",
                (str(new_cash), str(realized_total + realized), now),
            )
            db.execute(
                "INSERT INTO simulated_trades VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    execution_id,
                    decision_id,
                    strategy_run_id,
                    universe_run_id,
                    ticker,
                    now,
                    market_session.isoformat(),
                    side,
                    str(quantity),
                    str(price),
                    str(notional),
                    str(self.fee),
                    str(realized),
                    str(value_before),
                    str(value_after),
                    reason,
                    now,
                ),
            )
        return SimulatedTrade(
            execution_id, decision_id, ticker, side, quantity, price, notional, self.fee, realized
        )

    def snapshot(
        self, *, strategy_run_id: str, market_session: date, prices: dict[str, Decimal]
    ) -> dict[str, object]:
        existing = self.storage.row(
            "SELECT * FROM portfolio_snapshots WHERE market_session=?",
            (market_session.isoformat(),),
        )
        if existing:
            return existing
        cash, starting, realized = self.state()
        positions = self.positions()
        invested = sum(
            (quantity * prices[ticker] for ticker, (quantity, _) in positions.items()), Decimal("0")
        )
        cost = sum((quantity * average for quantity, average in positions.values()), Decimal("0"))
        unrealized = invested - cost
        total = cash + invested
        previous = self.storage.row(
            "SELECT total_value FROM portfolio_snapshots ORDER BY market_session DESC LIMIT 1"
        )
        previous_total = Decimal(previous["total_value"]) if previous else starting
        daily_pnl = total - previous_total
        daily_return = daily_pnl / previous_total if previous_total else Decimal("0")
        cumulative = (total - starting) / starting
        state = self.storage.row("SELECT portfolio_peak FROM portfolio_state WHERE singleton=1")
        peak = max(Decimal(state["portfolio_peak"]), total) if state else total
        drawdown = (peak - total) / peak if peak else Decimal("0")
        now = datetime.now(UTC).isoformat()
        snapshot = {
            "id": new_id("snapshot"),
            "strategy_run_id": strategy_run_id,
            "market_session": market_session.isoformat(),
            "cash": str(cash),
            "invested_value": str(invested),
            "total_value": str(total),
            "realized_pnl": str(realized),
            "unrealized_pnl": str(unrealized),
            "daily_pnl": str(daily_pnl),
            "daily_return": str(daily_return),
            "cumulative_return": str(cumulative),
            "positions_count": len(positions),
            "portfolio_peak": str(peak),
            "drawdown": str(drawdown),
            "created_at": now,
        }
        with self.storage.transaction() as db:
            db.execute(
                "UPDATE portfolio_state SET portfolio_peak=?, updated_at=? WHERE singleton=1",
                (str(peak), now),
            )
            db.execute(
                "INSERT INTO portfolio_snapshots VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(snapshot.values()),
            )
        return snapshot
