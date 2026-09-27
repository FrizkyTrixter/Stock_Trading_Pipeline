"""Deterministic universe policy; agent proposals cannot bypass it."""

from __future__ import annotations

from collections import Counter
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
    ai_infra_enabled: bool = False
    ai_infra_categories: frozenset[str] = frozenset()
    ai_infra_min_per_category: dict[str, int] | None = None
    ai_infra_max_per_category: dict[str, int] | None = None
    ai_infra_target_counts: dict[str, int] | None = None
    ai_infra_allow_multi_tag: bool = True


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
            reasons.extend(self._enforce_ai_infra_membership(candidate))
            reasons.extend(self._enforce_feedback_loop_metadata(candidate))
            if reasons:
                rejected[ticker] = tuple(reasons)
            else:
                candidates[ticker] = candidate

        accepted: list[str] = []
        accepted_candidates: list[TickerCandidate] = []
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
            accepted_candidates.append(candidate)
            sector_counts[candidate.sector] = projected

        mix_rejections = self._enforce_ai_infra_category_mix(tuple(accepted_candidates))
        for ticker, reasons in mix_rejections.items():
            if ticker in accepted:
                accepted.remove(ticker)
            rejected[ticker] = rejected.get(ticker, ()) + reasons

        return UniverseDecision(
            run_id=proposal.run_id,
            correlation_id=proposal.correlation_id,
            causation_id=proposal.id,
            accepted=tuple(accepted),
            rejected=rejected,
            provenance=(sha256_json(proposal.model_dump(mode="json")),),
            status="validated",
        )

    def _enforce_ai_infra_membership(self, candidate: TickerCandidate) -> tuple[str, ...]:
        if not self.config.ai_infra_enabled:
            return ()
        categories = tuple(item for item in candidate.categories if item)
        reasons: list[str] = []
        if not categories:
            reasons.append("ai_infra_membership_missing")
            return tuple(reasons)
        if not self.config.ai_infra_allow_multi_tag and len(categories) > 1:
            reasons.append("ai_infra_multi_tag_disallowed")
        if self.config.ai_infra_categories and any(
            category not in self.config.ai_infra_categories for category in categories
        ):
            reasons.append("ai_infra_category_not_allowed")
        return tuple(reasons)

    def _enforce_feedback_loop_metadata(self, candidate: TickerCandidate) -> tuple[str, ...]:
        if not self.config.ai_infra_enabled:
            return ()
        if not candidate.rationale.strip():
            return ("feedback_loop_metadata_missing",)
        return ()

    def _enforce_ai_infra_category_mix(
        self, accepted: tuple[TickerCandidate, ...]
    ) -> dict[str, tuple[str, ...]]:
        if not self.config.ai_infra_enabled:
            return {}

        counts: Counter[str] = Counter(tag for item in accepted for tag in item.categories)
        min_cfg = self.config.ai_infra_min_per_category or {}
        max_cfg = self.config.ai_infra_max_per_category or {}
        target_cfg = self.config.ai_infra_target_counts or {}

        under_min = {
            category for category, minimum in min_cfg.items() if counts.get(category, 0) < minimum
        }
        over_max = {
            category for category, maximum in max_cfg.items() if counts.get(category, 0) > maximum
        }
        over_target = {
            category for category, target in target_cfg.items() if counts.get(category, 0) > target
        }

        if not under_min and not over_max and not over_target:
            return {}

        rejected: dict[str, tuple[str, ...]] = {}
        for candidate in accepted:
            reasons: list[str] = []
            if any(category in candidate.categories for category in under_min):
                reasons.append("ai_infra_category_minimum_not_met")
            if any(category in candidate.categories for category in over_max):
                reasons.append("ai_infra_category_maximum_exceeded")
            if any(category in candidate.categories for category in over_target):
                reasons.append("ai_infra_category_target_exceeded")
            if reasons:
                rejected[candidate.ticker] = tuple(dict.fromkeys(reasons))
        return rejected
