"""Deterministic capital allocation; no LLM participates in sizing."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True)
class Allocation:
    ticker: str
    probability: Decimal
    target_notional: Decimal
    target_weight: Decimal
    action: str


class CapitalAllocationPolicy:
    def __init__(
        self,
        *,
        threshold: Decimal,
        max_positions: int,
        max_position_weight: Decimal,
        max_position_notional: Decimal,
        cash_reserve: Decimal = Decimal("0"),
    ) -> None:
        self.threshold = threshold
        self.max_positions = max_positions
        self.max_position_weight = max_position_weight
        self.max_position_notional = max_position_notional
        self.cash_reserve = cash_reserve

    def allocate(
        self,
        probabilities: dict[str, Decimal],
        portfolio_value: Decimal,
        current: dict[str, Decimal] | None = None,
    ) -> tuple[Allocation, ...]:
        current = current or {}
        qualified = sorted(
            ((ticker, score) for ticker, score in probabilities.items() if score >= self.threshold),
            key=lambda item: (-item[1], item[0]),
        )[: self.max_positions]
        if not qualified:
            return ()
        investable = max(Decimal("0"), portfolio_value - self.cash_reserve)
        score_total = sum((score for _, score in qualified), Decimal("0"))
        allocations: list[Allocation] = []
        for ticker, score in qualified:
            raw_weight = score / score_total
            weight = min(raw_weight, self.max_position_weight)
            target = min(investable * weight, self.max_position_notional).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            existing = current.get(ticker, Decimal("0"))
            action = "BUY" if existing < target else "REDUCE" if existing > target else "HOLD"
            allocations.append(Allocation(ticker, score, target, weight, action))
        return tuple(allocations)
