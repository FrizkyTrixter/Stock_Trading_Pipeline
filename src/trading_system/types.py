"""Strict, versioned domain contracts shared by every system boundary."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .clock import ensure_aware, utc_now
from .ids import new_id


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Record(StrictModel):
    schema_version: str = "1.0.0"
    id: str = Field(default_factory=lambda: new_id("rec"))
    run_id: str = Field(default_factory=lambda: new_id("run"))
    correlation_id: str = Field(default_factory=lambda: new_id("corr"))
    causation_id: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    source: str = "trading-system"
    producer_version: str = "0.1.0"
    data_as_of: datetime = Field(default_factory=utc_now)
    status: str = "created"
    validation_errors: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()

    @field_validator("timestamp", "data_as_of")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class Direction(StrEnum):
    STRONGLY_BEARISH = "strongly_bearish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    STRONGLY_BULLISH = "strongly_bullish"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class TickerCandidate(Record):
    ticker: str
    company_name: str
    exchange: str
    sector: str
    industry: str = "unknown"
    instrument_type: str = "common_stock"
    price: Decimal
    market_cap: Decimal | None = None
    average_daily_dollar_volume: Decimal
    trading_history_days: int
    listing_status: str = "active"
    rationale: str
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    confidence: Decimal = Decimal("0")

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or len(normalized) > 12:
            raise ValueError("Invalid ticker")
        return normalized


class UniverseProposal(Record):
    candidates: tuple[TickerCandidate, ...]


class UniverseDecision(Record):
    accepted: tuple[str, ...]
    rejected: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    previous_universe_hash: str | None = None


class MarketBar(StrictModel):
    ticker: str
    session: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adjusted: bool = True
    provider: str

    @field_validator("session")
    @classmethod
    def session_aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class MarketDataSnapshot(Record):
    bars: tuple[MarketBar, ...]
    content_hash: str
    quality_warnings: tuple[str, ...] = ()


class FeatureSnapshot(Record):
    ticker: str
    features: dict[str, float]
    feature_manifest_hash: str


class TrainingDatasetManifest(Record):
    dataset_hash: str
    feature_manifest_hash: str
    target: str
    prediction_horizon_sessions: int = 50
    return_threshold: Decimal = Decimal("0.10")
    embargo_sessions: int = 50
    row_count: int


class ModelMetadata(Record):
    model_id: str
    training_run_id: str
    code_commit: str = "unavailable"
    dataset_hash: str
    feature_manifest_hash: str
    training_period: tuple[str, str]
    validation_periods: tuple[tuple[str, str], ...]
    test_period: tuple[str, str] | None = None
    hyperparameters: dict[str, Any]
    metrics: dict[str, float | int | None]
    calibration_metadata: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str
    artifact_hash: str
    approval_state: str = "candidate"
    known_limitations: tuple[str, ...] = ()


class ModelEvaluation(Record):
    model_id: str
    metrics: dict[str, float | int | None]
    baseline_metrics: dict[str, float | int | None]
    promotion_eligible: bool
    reasons: tuple[str, ...] = ()


class ModelSignal(Record):
    ticker: str
    model_id: str
    feature_snapshot_id: str
    positive_class_probability: Decimal = Field(ge=0, le=1)
    calibrated_probability: Decimal | None = Field(default=None, ge=0, le=1)
    predicted_class: int
    rank: int
    score_percentile: Decimal = Field(ge=0, le=1)
    major_contributing_features: tuple[str, ...] = ()
    warning_flags: tuple[str, ...] = ()
    missing_features: tuple[str, ...] = ()


class NewsArticle(Record):
    article_id: str
    canonical_url: str
    provider: str
    headline: str
    publication: str
    author: str | None = None
    publication_timestamp: datetime
    retrieval_timestamp: datetime
    tickers: tuple[str, ...]
    excerpt: str
    content_hash: str
    language: str = "en"
    deduplication_key: str

    @field_validator("publication_timestamp", "retrieval_timestamp")
    @classmethod
    def news_time_aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class NewsEvidence(StrictModel):
    article_id: str
    summary: str
    claim_kind: str


class NewsAssessment(Record):
    ticker: str
    evidence: tuple[NewsEvidence, ...]
    bullish_evidence_ids: tuple[str, ...] = ()
    bearish_evidence_ids: tuple[str, ...] = ()
    neutral_evidence_ids: tuple[str, ...] = ()
    event_categories: tuple[str, ...] = ()
    expected_direction: Direction
    expected_horizon: str
    confidence: Decimal = Field(ge=0, le=1)
    disagreement_score: Decimal = Field(ge=0, le=1)
    freshness: Decimal = Field(ge=0, le=1)
    source_diversity: int = 0
    materiality: Decimal = Field(ge=0, le=1)
    uncertainty: str


class AgentRun(Record):
    agent_name: str
    agent_version: str
    prompt_template_version: str
    model_provider: str
    model_name: str
    sanitized_input: dict[str, Any]
    output: dict[str, Any]
    validation_result: str
    usage_metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int
    retry_count: int = 0
    evidence_references: tuple[str, ...] = ()


class AgentDecision(Record):
    agent_run_id: str
    decision_type: str
    decision: dict[str, Any]


class ERPEvent(StrictModel):
    event_external_id: str
    event_type: str
    effective_at: datetime
    currency: str
    symbol: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    gross_amount: Decimal | None = None
    fee_amount: Decimal = Decimal("0")
    net_amount: Decimal | None = None
    order_id: str | None = None
    fill_id: str | None = None
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str

    @field_validator("effective_at")
    @classmethod
    def effective_aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class ERPExportBatch(Record):
    batch_id: str
    source_system: str = "stock-trading-pipeline"
    account_external_id: str
    events: tuple[ERPEvent, ...]
    content_hash: str
    signature: str | None = None


class ERPImportResult(Record):
    batch_id: str
    imported: int
    skipped: int
    errors: tuple[str, ...] = ()
