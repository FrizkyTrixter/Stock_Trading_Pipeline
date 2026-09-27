"""Monthly LLM research with exact-100 validation and versioned persistence."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .ai_feedback_loop import AIInfraCategory, build_category_targets
from .config import AIInfrastructurePolicyConfig
from .ids import new_id
from .market_data import MarketDataProvider
from .storage import Storage

TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,11}$")
_VALID_AI_CATEGORIES = frozenset(item.value for item in AIInfraCategory)


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str
    publisher: str
    url: HttpUrl
    published_at: datetime | None = None


class ResearchMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ticker: str
    company_name: str
    rank: int = Field(ge=1, le=100)
    sector: str
    category: str
    reason: str
    thesis: str
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    sources: tuple[ResearchSource, ...] = ()
    categories: tuple[str, ...] = ()
    feedback_loop_rationale: str | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not TICKER.fullmatch(value):
            raise ValueError("malformed ticker")
        return value

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
        unknown = sorted(item for item in normalized if item not in _VALID_AI_CATEGORIES)
        if unknown:
            raise ValueError(f"unknown AI infrastructure categories: {', '.join(unknown)}")
        return normalized


class UniverseResearchProvider(Protocol):
    provider_name: str
    model_name: str

    def research(
        self, prompt: str, *, repair_feedback: str | None = None
    ) -> list[dict[str, Any]]: ...


class OpenAIUniverseResearchProvider:
    provider_name = "openai"

    def __init__(self, model_name: str, client: Any | None = None) -> None:
        self.model_name = model_name
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self.client = client

    def research(self, prompt: str, *, repair_feedback: str | None = None) -> list[dict[str, Any]]:
        request = (
            prompt
            if repair_feedback is None
            else f"{prompt}\n\nREPAIR REQUIRED:\n{repair_feedback}"
        )
        response = self.client.responses.create(
            model=self.model_name,
            input=request,
            tools=[{"type": "web_search"}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "monthly_universe",
                    "strict": True,
                    "schema": universe_json_schema(),
                }
            },
        )
        payload = json.loads(response.output_text)
        return list(payload["stocks"])


def universe_json_schema() -> dict[str, Any]:
    source = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "publisher": {"type": "string"},
            "url": {"type": "string"},
            "published_at": {"type": ["string", "null"]},
        },
        "required": ["title", "publisher", "url", "published_at"],
    }
    member = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ticker": {"type": "string"},
            "company_name": {"type": "string"},
            "rank": {"type": "integer"},
            "sector": {"type": "string"},
            "category": {"type": "string"},
            "reason": {"type": "string"},
            "thesis": {"type": "string"},
            "catalysts": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": ["number", "null"]},
            "sources": {"type": "array", "items": source},
            "categories": {"type": "array", "items": {"type": "string"}},
            "feedback_loop_rationale": {"type": ["string", "null"]},
        },
        "required": [
            "ticker",
            "company_name",
            "rank",
            "sector",
            "category",
            "reason",
            "thesis",
            "catalysts",
            "risks",
            "confidence",
            "sources",
            "categories",
            "feedback_loop_rationale",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "stocks": {"type": "array", "minItems": 100, "maxItems": 100, "items": member}
        },
        "required": ["stocks"],
    }


class UniverseResearchService:
    prompt_version = "monthly-universe-v3"

    def __init__(
        self,
        storage: Storage,
        market_data: MarketDataProvider,
        provider: UniverseResearchProvider,
        theme: str,
        universe_size: int = 100,
        ai_infrastructure: AIInfrastructurePolicyConfig | None = None,
    ) -> None:
        self.storage = storage
        self.market_data = market_data
        self.provider = provider
        self.theme = theme
        self.universe_size = universe_size
        self.ai_infrastructure = ai_infrastructure or AIInfrastructurePolicyConfig()

    @staticmethod
    def period_for(value: date | None = None) -> str:
        value = value or datetime.now(UTC).date()
        return value.strftime("%Y-%m")

    def prompt(self, period: str) -> str:
        return (
            f"Which exactly 100 publicly traded stocks should this quantitative strategy actively "
            f"monitor during {period} based on the investment thesis '{self.theme}' and current "
            "available information? Return unique common-stock tickers, company, rank 1-100, "
            "sector, category, concise reason, thesis, catalysts, risks, confidence, real "
            "verifiable source metadata, AI-infrastructure category tags, and a one-line "
            "feedback-loop rationale. Do not invent URLs. AI researches; it does not size "
            "or execute trades."
        )

    def run(self, *, period: str | None = None, force: bool = False, max_attempts: int = 3) -> str:
        period = period or self.period_for()
        existing = self.storage.row("SELECT * FROM universe_runs WHERE period=?", (period,))
        if existing and not force:
            return str(existing["id"])
        feedback: str | None = None
        last_error: Exception | None = None
        for _ in range(max_attempts):
            try:
                raw = self.provider.research(self.prompt(period), repair_feedback=feedback)
                members = self.validate(raw)
                return self.persist(period, members, replace=bool(existing and force))
            except (ValueError, MarketDataErrorProxy) as exc:
                last_error = exc
                feedback = str(exc)
        raise ValueError(f"Could not create an exact valid universe: {last_error}")

    def build_ai_infra_candidate_pool(self, as_of_date: date) -> tuple[dict[str, Any], ...]:
        period = self.period_for(as_of_date)
        run = self.storage.row(
            "SELECT id FROM universe_runs WHERE status='completed' AND period<=? "
            "ORDER BY period DESC LIMIT 1",
            (period,),
        )
        if run is None:
            return ()
        rows = self.storage.universe_members(str(run["id"]))
        scored: list[dict[str, Any]] = []
        for row in rows:
            copy = dict(row)
            copy["categories"] = tuple(json.loads(copy.get("ai_infra_categories_json") or "[]"))
            copy["score"] = self.score_ai_feedback_alignment(copy)
            scored.append(copy)
        scored.sort(key=lambda item: (-item["score"], int(item["rank"]), str(item["ticker"])))
        return tuple(scored)

    def score_ai_feedback_alignment(self, candidate: ResearchMember | dict[str, Any]) -> Decimal:
        if isinstance(candidate, ResearchMember):
            categories = candidate.categories
            confidence = candidate.confidence or Decimal("0")
        else:
            categories = tuple(str(item) for item in candidate.get("categories") or ())
            raw = candidate.get("confidence")
            confidence = Decimal(str(raw)) if raw is not None else Decimal("0")
        category_score = Decimal(len(set(categories))) / Decimal(max(len(_VALID_AI_CATEGORIES), 1))
        return (category_score + confidence) / Decimal("2")

    def validate(self, raw: list[dict[str, Any]]) -> tuple[ResearchMember, ...]:
        members = tuple(ResearchMember.model_validate(item) for item in raw)
        if len(members) != self.universe_size:
            raise ValueError(
                f"expected exactly {self.universe_size} stocks, received {len(members)}"
            )
        tickers = [item.ticker for item in members]
        if len(set(tickers)) != self.universe_size:
            duplicates = sorted({ticker for ticker in tickers if tickers.count(ticker) > 1})
            raise ValueError("duplicate tickers: " + ", ".join(duplicates))
        if sorted(item.rank for item in members) != list(range(1, self.universe_size + 1)):
            raise ValueError("ranks must be unique and cover 1 through 100")

        if self.ai_infrastructure.enabled:
            if not self.ai_infrastructure.allow_multi_tag:
                multi = sorted(item.ticker for item in members if len(item.categories) > 1)
                if multi:
                    raise ValueError("multi-tagged members are not allowed: " + ", ".join(multi))
            untagged = sorted(item.ticker for item in members if not item.categories)
            if untagged:
                raise ValueError("untagged AI-infra members: " + ", ".join(untagged))
            allowed = set(self.ai_infrastructure.categories)
            unknown = sorted(
                {
                    category
                    for member in members
                    for category in member.categories
                    if allowed and category not in allowed
                }
            )
            if unknown:
                raise ValueError("categories outside configured AI infra list: " + ", ".join(unknown))
            counts: Counter[str] = Counter(
                category for member in members for category in member.categories
            )
            for category, minimum in self.ai_infrastructure.min_per_category.items():
                if counts.get(category, 0) < minimum:
                    raise ValueError(
                        f"category {category} below minimum {minimum}: {counts.get(category, 0)}"
                    )
            for category, maximum in self.ai_infrastructure.max_per_category.items():
                if counts.get(category, 0) > maximum:
                    raise ValueError(
                        f"category {category} above maximum {maximum}: {counts.get(category, 0)}"
                    )
            build_category_targets(self.ai_infrastructure)

        prices = self.market_data.latest(tickers)
        invalid = sorted(
            ticker for ticker in tickers if ticker not in prices or not prices[ticker].available
        )
        if invalid:
            raise ValueError("Yahoo-unavailable tickers must be replaced: " + ", ".join(invalid))
        return tuple(sorted(members, key=lambda item: item.rank))

    def persist(self, period: str, members: tuple[ResearchMember, ...], *, replace: bool) -> str:
        run_id = new_id("universe")
        now = datetime.now(UTC).isoformat()
        with self.storage.transaction() as db:
            if replace:
                db.execute("UPDATE universe_runs SET status='superseded' WHERE period=?", (period,))
                db.execute(
                    "UPDATE universe_runs SET period=period || '-superseded-' || id WHERE period=?",
                    (period,),
                )
            db.execute(
                "INSERT INTO universe_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    run_id,
                    period,
                    "default",
                    now,
                    self.provider.provider_name,
                    self.provider.model_name,
                    self.prompt_version,
                    "completed",
                ),
            )
            for item in members:
                db.execute(
                    "INSERT INTO universe_members ("
                    "universe_run_id, ticker, company_name, rank, sector, category, reason, thesis, "
                    "catalysts_json, risks_json, confidence, researched_at, ai_infra_categories_json, "
                    "feedback_loop_rationale"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        item.ticker,
                        item.company_name,
                        item.rank,
                        item.sector,
                        item.category,
                        item.reason,
                        item.thesis,
                        json.dumps(item.catalysts),
                        json.dumps(item.risks),
                        str(item.confidence) if item.confidence is not None else None,
                        now,
                        json.dumps(item.categories),
                        item.feedback_loop_rationale,
                    ),
                )
                for source in item.sources:
                    db.execute(
                        "INSERT OR IGNORE INTO research_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            new_id("source"),
                            run_id,
                            item.ticker,
                            source.title,
                            source.publisher,
                            str(source.url),
                            source.published_at.isoformat() if source.published_at else None,
                            now,
                        ),
                    )
        return run_id


class MarketDataErrorProxy(Exception):
    """Compatibility marker for provider validation failures."""
