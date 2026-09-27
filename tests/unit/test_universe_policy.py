from decimal import Decimal

from trading_system.types import TickerCandidate, UniverseProposal
from trading_system.universe import UniversePolicy, UniversePolicyConfig


def _candidate(ticker: str, **changes: object) -> TickerCandidate:
    payload = {
        "ticker": ticker,
        "company_name": f"{ticker} Corp",
        "exchange": "NASDAQ",
        "sector": "Technology",
        "price": Decimal("20"),
        "market_cap": Decimal("1000000000"),
        "average_daily_dollar_volume": Decimal("20000000"),
        "trading_history_days": 1000,
        "rationale": "feedback loop metadata",
        "confidence": Decimal("0.9"),
        "categories": ("chips_semiconductors",),
    }
    payload.update(changes)
    return TickerCandidate(**payload)


def test_ai_infra_membership_rejection() -> None:
    policy = UniversePolicy(UniversePolicyConfig(ai_infra_enabled=True))
    decision = policy.evaluate(
        UniverseProposal(candidates=(_candidate("AAA", categories=()),))
    )
    assert "ai_infra_membership_missing" in decision.rejected["AAA"]


def test_ai_infra_mix_rejection() -> None:
    policy = UniversePolicy(
        UniversePolicyConfig(
            ai_infra_enabled=True,
            ai_infra_target_counts={"chips_semiconductors": 1},
        )
    )
    decision = policy.evaluate(
        UniverseProposal(candidates=(_candidate("AAA"), _candidate("BBB")))
    )
    assert decision.accepted == ()
    assert "ai_infra_category_target_exceeded" in decision.rejected["AAA"]
    assert "ai_infra_category_target_exceeded" in decision.rejected["BBB"]


def test_feedback_loop_metadata_gate() -> None:
    policy = UniversePolicy(UniversePolicyConfig(ai_infra_enabled=True))
    decision = policy.evaluate(
        UniverseProposal(candidates=(_candidate("AAA", rationale="   "),))
    )
    assert "feedback_loop_metadata_missing" in decision.rejected["AAA"]


def test_ai_infra_disabled_preserves_previous_behavior() -> None:
    policy = UniversePolicy()
    decision = policy.evaluate(
        UniverseProposal(candidates=(_candidate("AAA", categories=(), rationale=""),))
    )
    assert decision.accepted == ("AAA",)
