"""Monthly LLM research with exact-100 validation and versioned persistence."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .ids import new_id
from .market_data import MarketDataProvider
from .storage import Storage

TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,11}$")


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

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not TICKER.fullmatch(value):
            raise ValueError("malformed ticker")
        return value


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
    prompt_version = "monthly-universe-v2"

    def __init__(
        self,
        storage: Storage,
        market_data: MarketDataProvider,
        provider: UniverseResearchProvider,
        theme: str,
        universe_size: int = 100,
    ) -> None:
        self.storage = storage
        self.market_data = market_data
        self.provider = provider
        self.theme = theme
        self.universe_size = universe_size

    @staticmethod
    def period_for(value: date | None = None) -> str:
        value = value or datetime.now(UTC).date()
        return value.strftime("%Y-%m")

    def prompt(self, period: str) -> str:
        return (
            f"Which exactly 100 publicly traded stocks should this quantitative strategy actively "
            f"monitor during {period} based on the investment thesis '{self.theme}' and current "
            "available information? Return unique common-stock tickers, company, rank 1-100, "
            "sector, category, concise reason, thesis, catalysts, risks, confidence, and real "
            "verifiable source "
            "metadata. Do not invent URLs. AI researches; it does not size or execute trades."
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
                    "INSERT INTO universe_members VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
