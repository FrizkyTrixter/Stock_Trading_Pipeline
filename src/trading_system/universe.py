"""Deterministic universe policy; agent proposals cannot bypass it."""

from dataclasses import dataclass
from decimal import Decimal

from .security import sha256_json
from .types import TickerCandidate, UniverseDecision, UniverseProposal


@dataclass(frozen=True)
class UniversePolicyConfig:
    allowed_exchanges: frozenset[str] = frozenset({"NYSE", "NASDAQ", "TSX"})
    allowed_instrument_types: frozenset[str] = frozenset({"common_stock"})
    minimum_price: Decimal = Decimal("5")
    minimum_market_cap: Decimal = Decimal("100000000")
    minimum_average_dollar_volume: Decimal = Decimal("5000000")
    minimum_trading_history_days: int = 252
    maximum_symbols: int = 100
    maximum_sector_fraction: Decimal = Decimal("0.35")
    allow_list: frozenset[str] = frozenset()
    deny_list: frozenset[str] = frozenset()


class UniversePolicy:
    def __init__(self, config: UniversePolicyConfig | None = None) -> None:
        self.config = config or UniversePolicyConfig()

    def evaluate(self, proposal: UniverseProposal) -> UniverseDecision:
        rejected: dict[str, tuple[str, ...]] = {}
        candidates: dict[str, TickerCandidate] = {}
        for candidate in proposal.candidates:
            ticker = candidate.ticker
            reasons: list[str] = []
            if ticker in candidates:
                reasons.append("duplicate_symbol")
            if self.config.allow_list and ticker not in self.config.allow_list:
                reasons.append("not_allow_listed")
            if ticker in self.config.deny_list:
                reasons.append("deny_listed")
            if candidate.exchange.upper() not in self.config.allowed_exchanges:
                reasons.append("exchange_not_allowed")
            if candidate.instrument_type not in self.config.allowed_instrument_types:
                reasons.append("instrument_type_not_allowed")
            if candidate.listing_status != "active":
                reasons.append("listing_not_active")
            if candidate.price < self.config.minimum_price:
                reasons.append("price_below_minimum")
            if (
                candidate.market_cap is None
                or candidate.market_cap < self.config.minimum_market_cap
            ):
                reasons.append("market_cap_below_minimum")
            if candidate.average_daily_dollar_volume < self.config.minimum_average_dollar_volume:
                reasons.append("liquidity_below_minimum")
            if candidate.trading_history_days < self.config.minimum_trading_history_days:
                reasons.append("trading_history_too_short")
            if reasons:
                rejected[ticker] = tuple(reasons)
            else:
                candidates[ticker] = candidate

        accepted: list[str] = []
        sector_counts: dict[str, int] = {}
        for candidate in sorted(
            candidates.values(), key=lambda item: (-item.confidence, item.ticker)
        ):
            if len(accepted) >= self.config.maximum_symbols:
                rejected[candidate.ticker] = ("maximum_symbols_exceeded",)
                continue
            projected = sector_counts.get(candidate.sector, 0) + 1
            projected_total = len(accepted) + 1
            if (
                Decimal(projected) / Decimal(projected_total) > self.config.maximum_sector_fraction
                and projected_total > 2
            ):
                rejected[candidate.ticker] = ("sector_concentration_limit",)
                continue
            accepted.append(candidate.ticker)
            sector_counts[candidate.sector] = projected

        return UniverseDecision(
            run_id=proposal.run_id,
            correlation_id=proposal.correlation_id,
            causation_id=proposal.id,
            accepted=tuple(accepted),
            rejected=rejected,
            provenance=(sha256_json(proposal.model_dump(mode="json")),),
            status="validated",
        )
