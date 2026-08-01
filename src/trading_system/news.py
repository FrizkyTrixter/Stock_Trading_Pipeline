"""News retrieval is separated from injection-resistant structured interpretation."""

from dataclasses import dataclass
from datetime import UTC, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from defusedxml import ElementTree

from .clock import utc_now
from .ids import new_id
from .security import contains_prompt_injection, sha256_json
from .types import Direction, NewsArticle, NewsAssessment, NewsEvidence


class NewsProvider(Protocol):
    name: str

    def collect(self, tickers: tuple[str, ...]) -> tuple[NewsArticle, ...]: ...


@dataclass(frozen=True)
class FixtureNewsProvider:
    articles: tuple[NewsArticle, ...]
    name: str = "fixture"

    def collect(self, tickers: tuple[str, ...]) -> tuple[NewsArticle, ...]:
        selected = set(tickers)
        return tuple(article for article in self.articles if selected.intersection(article.tickers))


@dataclass(frozen=True)
class RssNewsProvider:
    """Read-only RSS fallback storing only provider-permitted feed excerpts."""

    feeds_by_ticker: dict[str, tuple[str, ...]]
    timeout_seconds: float = 10.0
    name: str = "rss"

    def collect(self, tickers: tuple[str, ...]) -> tuple[NewsArticle, ...]:
        articles: list[NewsArticle] = []
        retrieval = utc_now()
        for ticker in tickers:
            for feed_url in self.feeds_by_ticker.get(ticker, ()):
                if urlparse(feed_url).scheme not in {"https", "http"}:
                    raise ValueError("RSS feeds must use HTTP or HTTPS")
                request = Request(  # noqa: S310 - scheme allow-listed above
                    feed_url, headers={"User-Agent": "safe-trading-research/0.1"}
                )
                with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                    document = ElementTree.fromstring(response.read(2_000_000))
                for item in document.findall(".//item")[:50]:
                    headline = (item.findtext("title") or "Untitled").strip()
                    link = (item.findtext("link") or feed_url).strip()
                    excerpt = (item.findtext("description") or "").strip()[:1000]
                    published_text = item.findtext("pubDate")
                    published = retrieval
                    if published_text:
                        try:
                            published = parsedate_to_datetime(published_text).astimezone(UTC)
                        except (TypeError, ValueError, OverflowError):
                            published = retrieval
                    content_hash = sha256_json(
                        {"headline": headline, "link": link, "excerpt": excerpt}
                    )
                    articles.append(
                        NewsArticle(
                            article_id=new_id("article"),
                            canonical_url=link,
                            provider=self.name,
                            publication=self.name,
                            headline=headline,
                            publication_timestamp=published,
                            retrieval_timestamp=retrieval,
                            tickers=(ticker,),
                            excerpt=excerpt,
                            content_hash=content_hash,
                            deduplication_key=sha256_json(
                                {"headline": headline.casefold(), "link": link}
                            ),
                            status="collected",
                        )
                    )
        return tuple(articles)


def deduplicate_and_filter(
    articles: tuple[NewsArticle, ...], recency: timedelta = timedelta(days=3)
) -> tuple[NewsArticle, ...]:
    cutoff = utc_now() - recency
    unique: dict[str, NewsArticle] = {}
    for article in sorted(articles, key=lambda item: item.publication_timestamp, reverse=True):
        if article.publication_timestamp < cutoff:
            continue
        unique.setdefault(article.deduplication_key, article)
    return tuple(unique.values())


class DeterministicNewsAnalyzer:
    """Fixture-safe analyzer; production LLM adapters must return the same strict schema."""

    POSITIVE = ("beats", "growth", "contract", "approval", "upgrade", "expands")
    NEGATIVE = ("misses", "decline", "lawsuit", "downgrade", "outage", "recall")

    def analyze(self, ticker: str, articles: tuple[NewsArticle, ...]) -> NewsAssessment:
        related = [article for article in articles if ticker in article.tickers]
        evidence: list[NewsEvidence] = []
        bullish: list[str] = []
        bearish: list[str] = []
        providers: set[str] = set()
        for article in related:
            providers.add(article.provider)
            untrusted = f"{article.headline} {article.excerpt}"
            if contains_prompt_injection(untrusted):
                summary = (
                    "Article excluded from directional inference due to injection-like content."
                )
                kind = "untrusted_instruction"
            else:
                lowered = untrusted.casefold()
                positive = sum(term in lowered for term in self.POSITIVE)
                negative = sum(term in lowered for term in self.NEGATIVE)
                kind = "reported_fact_or_source_claim"
                summary = article.headline[:240]
                if positive > negative:
                    bullish.append(article.article_id)
                elif negative > positive:
                    bearish.append(article.article_id)
            evidence.append(
                NewsEvidence(article_id=article.article_id, summary=summary, claim_kind=kind)
            )
        if not evidence:
            direction = Direction.INSUFFICIENT_EVIDENCE
            confidence = Decimal("0")
        elif len(bullish) > len(bearish):
            direction = Direction.BULLISH
            confidence = Decimal("0.60")
        elif len(bearish) > len(bullish):
            direction = Direction.BEARISH
            confidence = Decimal("0.60")
        else:
            direction = Direction.NEUTRAL
            confidence = Decimal("0.40")
        return NewsAssessment(
            ticker=ticker,
            evidence=tuple(evidence),
            bullish_evidence_ids=tuple(bullish),
            bearish_evidence_ids=tuple(bearish),
            expected_direction=direction,
            expected_horizon="1-10 sessions",
            confidence=confidence,
            disagreement_score=Decimal("1") if bullish and bearish else Decimal("0"),
            freshness=Decimal("1") if evidence else Decimal("0"),
            source_diversity=len(providers),
            materiality=Decimal("0.5") if evidence else Decimal("0"),
            uncertainty="Deterministic keyword fixture analysis; no unsupported claims added.",
            status="analyzed" if evidence else "insufficient_evidence",
            provenance=tuple(item.article_id for item in evidence),
        )


def validate_evidence(assessment: NewsAssessment, articles: tuple[NewsArticle, ...]) -> None:
    known = {article.article_id for article in articles}
    cited = {evidence.article_id for evidence in assessment.evidence}
    if not cited.issubset(known):
        raise ValueError(f"Fabricated evidence IDs: {sorted(cited - known)}")
