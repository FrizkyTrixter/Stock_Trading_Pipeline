"""Transparent conservative decision policy; it produces recommendations, never orders."""

from datetime import timedelta
from decimal import Decimal

from .clock import utc_now
from .ids import new_id
from .types import (
    Direction,
    ModelSignal,
    NewsAssessment,
    PortfolioSnapshot,
    RecommendationAction,
    TradeRecommendation,
)


class DecisionPolicy:
    def __init__(
        self,
        probability_threshold: Decimal = Decimal("0.60"),
        maximum_uncertainty: Decimal = Decimal("0.40"),
        default_notional: Decimal = Decimal("1000"),
    ) -> None:
        self.probability_threshold = probability_threshold
        self.maximum_uncertainty = maximum_uncertainty
        self.default_notional = default_notional

    def recommend(
        self,
        signal: ModelSignal,
        news: NewsAssessment | None,
        portfolio: PortfolioSnapshot,
    ) -> TradeRecommendation:
        probability = signal.calibrated_probability or signal.positive_class_probability
        action = RecommendationAction.BUY
        conflicts: list[str] = []
        abstention: str | None = None
        if signal.warning_flags or signal.missing_features:
            action, abstention = RecommendationAction.DEFER, "signal_warning_or_missing_features"
        elif probability < self.probability_threshold:
            action, abstention = RecommendationAction.AVOID, "model_probability_below_threshold"
        elif news and news.disagreement_score > self.maximum_uncertainty:
            action, abstention = RecommendationAction.DEFER, "news_uncertainty_above_threshold"
        elif (
            news
            and news.expected_direction in {Direction.BEARISH, Direction.STRONGLY_BEARISH}
            and news.materiality >= Decimal("0.5")
        ):
            action, abstention = RecommendationAction.AVOID, "material_bearish_news_veto"
            conflicts.append("model/news conflict")
        elif portfolio.cash <= 0:
            action, abstention = RecommendationAction.DEFER, "no_available_cash"
        return TradeRecommendation(
            recommendation_id=new_id("recommendation"),
            ticker=signal.ticker,
            action=action,
            rationale=(
                "Model signal is primary; current structured news can confirm, "
                "reduce, veto, or defer."
            ),
            model_signal_id=signal.id,
            news_assessment_id=news.id if news else None,
            conflicts=tuple(conflicts),
            provisional_notional=self.default_notional
            if action == RecommendationAction.BUY
            else None,
            confidence=probability,
            expected_horizon="50 sessions",
            invalidation_conditions=(
                "market data becomes stale",
                "kill switch activates",
                "model approval changes",
            ),
            expires_at=utc_now() + timedelta(hours=4),
            abstention_reason=abstention,
            status="recommended" if action == RecommendationAction.BUY else "abstained",
            data_as_of=min(signal.data_as_of, news.data_as_of) if news else signal.data_as_of,
        )
