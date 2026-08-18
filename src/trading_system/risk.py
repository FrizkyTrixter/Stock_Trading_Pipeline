"""Deterministic position sizing and machine-readable pre-trade risk checks."""

from decimal import ROUND_DOWN, Decimal

from .clock import utc_now
from .config import RiskLimits
from .ids import new_id
from .storage import Storage
from .types import (
    OrderIntent,
    PortfolioSnapshot,
    RecommendationAction,
    RiskAssessment,
    RiskCheck,
    RiskOutcome,
    TradeRecommendation,
)


def size_fixed_notional(
    recommendation: TradeRecommendation,
    reference_price: Decimal,
    available_cash: Decimal,
    fractional: bool = False,
    slippage_buffer: Decimal = Decimal("0.01"),
) -> Decimal:
    if reference_price <= 0:
        raise ValueError("Reference price must be positive")
    notional = min(recommendation.provisional_notional or Decimal("0"), available_cash)
    effective_price = reference_price * (Decimal("1") + slippage_buffer)
    quantity = notional / effective_price
    quantum = Decimal("0.000001") if fractional else Decimal("1")
    return quantity.quantize(quantum, rounding=ROUND_DOWN)


class RiskEngine:
    def __init__(self, limits: RiskLimits, storage: Storage) -> None:
        self.limits = limits
        self.storage = storage

    def evaluate(
        self,
        recommendation: TradeRecommendation,
        portfolio: PortfolioSnapshot,
        quantity: Decimal,
        reference_price: Decimal,
        model_id: str,
        market_data_fresh: bool = True,
        account_data_fresh: bool = True,
        sector: str = "unknown",
    ) -> tuple[RiskAssessment, OrderIntent | None]:
        notional = quantity * reference_price
        checks: list[RiskCheck] = []

        def check(name: str, passed: bool, value: object, threshold: object, reason: str) -> None:
            checks.append(
                RiskCheck(
                    name=name,
                    passed=passed,
                    input_value=str(value),
                    threshold=str(threshold),
                    reason="" if passed else reason,
                )
            )

        existing = next((p for p in portfolio.positions if p.ticker == recommendation.ticker), None)
        existing_notional = existing.quantity * existing.market_price if existing else Decimal("0")
        equity = portfolio.cash + sum(p.quantity * p.market_price for p in portfolio.positions)
        gross = sum(abs(p.quantity * p.market_price) for p in portfolio.positions) + notional
        sector_notional = (
            sum(abs(p.quantity * p.market_price) for p in portfolio.positions if p.sector == sector)
            + notional
        )
        check(
            "recommendation_action",
            recommendation.action == RecommendationAction.BUY,
            recommendation.action,
            "buy",
            "recommendation is not executable",
        )
        check("positive_quantity", quantity > 0, quantity, "> 0", "sized quantity is zero")
        check(
            "maximum_order_notional",
            notional <= self.limits.maximum_order_notional,
            notional,
            self.limits.maximum_order_notional,
            "order notional exceeds limit",
        )
        check(
            "maximum_position_notional",
            existing_notional + notional <= self.limits.maximum_position_notional,
            existing_notional + notional,
            self.limits.maximum_position_notional,
            "position notional exceeds limit",
        )
        check(
            "maximum_position_percent",
            equity > 0
            and (existing_notional + notional) / equity <= self.limits.maximum_position_percent,
            (existing_notional + notional) / equity if equity else "undefined",
            self.limits.maximum_position_percent,
            "position percentage exceeds limit",
        )
        check(
            "maximum_gross_exposure",
            equity > 0 and gross / equity <= self.limits.maximum_gross_exposure,
            gross / equity if equity else "undefined",
            self.limits.maximum_gross_exposure,
            "gross exposure exceeds limit",
        )
        check(
            "maximum_sector_exposure",
            equity > 0 and sector_notional / equity <= self.limits.maximum_sector_exposure,
            sector_notional / equity if equity else "undefined",
            self.limits.maximum_sector_exposure,
            "sector exposure exceeds limit",
        )
        new_position = existing is None and quantity > 0
        check(
            "maximum_open_positions",
            len(portfolio.positions) + int(new_position) <= self.limits.maximum_open_positions,
            len(portfolio.positions) + int(new_position),
            self.limits.maximum_open_positions,
            "open position limit reached",
        )
        check(
            "minimum_cash_reserve",
            portfolio.cash - notional >= self.limits.minimum_cash_reserve,
            portfolio.cash - notional,
            self.limits.minimum_cash_reserve,
            "cash reserve would be breached",
        )
        check(
            "maximum_daily_turnover",
            portfolio.daily_turnover + notional <= self.limits.maximum_daily_turnover,
            portfolio.daily_turnover + notional,
            self.limits.maximum_daily_turnover,
            "daily turnover limit breached",
        )
        check(
            "maximum_daily_realized_loss",
            portfolio.realized_pnl_today >= -self.limits.maximum_daily_realized_loss,
            portfolio.realized_pnl_today,
            -self.limits.maximum_daily_realized_loss,
            "daily loss limit breached",
        )
        check(
            "maximum_drawdown",
            portfolio.drawdown <= self.limits.maximum_drawdown,
            portfolio.drawdown,
            self.limits.maximum_drawdown,
            "drawdown limit breached",
        )
        check(
            "maximum_orders_per_day",
            portfolio.orders_today < self.limits.maximum_orders_per_day,
            portfolio.orders_today,
            self.limits.maximum_orders_per_day,
            "daily order count reached",
        )
        check(
            "market_data_fresh", market_data_fresh, market_data_fresh, True, "market data is stale"
        )
        check(
            "account_data_fresh",
            account_data_fresh,
            account_data_fresh,
            True,
            "account data is stale",
        )
        check(
            "restricted_symbol",
            recommendation.ticker not in self.limits.restricted_symbols,
            recommendation.ticker,
            "not restricted",
            "symbol is restricted",
        )
        check(
            "kill_switch",
            not self.storage.kill_switch_active(),
            self.storage.kill_switch_active(),
            False,
            "emergency kill switch is active",
        )
        failures = tuple(item.reason for item in checks if not item.passed)
        assessment_id = new_id("risk")
        outcome = RiskOutcome.APPROVAL_REQUIRED if not failures else RiskOutcome.REJECTED
        assessment = RiskAssessment(
            risk_assessment_id=assessment_id,
            recommendation_id=recommendation.recommendation_id,
            checks=tuple(checks),
            outcome=outcome,
            requested_quantity=quantity,
            approved_quantity=quantity if not failures else Decimal("0"),
            rejection_reasons=failures,
            status=outcome.value,
        )
        if failures:
            return assessment, None
        intent = OrderIntent(
            order_intent_id=new_id("intent"),
            recommendation_id=recommendation.recommendation_id,
            risk_assessment_id=assessment_id,
            model_id=model_id,
            ticker=recommendation.ticker,
            side="buy",
            quantity=quantity,
            limit_price=reference_price,
            maximum_notional=notional,
            idempotency_key=new_id("idem"),
            status="awaiting_approval",
            data_as_of=utc_now(),
        )
        return assessment, intent
