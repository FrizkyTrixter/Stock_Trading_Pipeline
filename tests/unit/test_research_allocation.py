from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from trading_system.allocation import CapitalAllocationPolicy
from trading_system.market_data import FakeMarketDataProvider
from trading_system.research import UniverseResearchService
from trading_system.storage import Storage


class Provider:
    provider_name = "fixture"
    model_name = "fixture-llm"

    def __init__(self, count=100, duplicate=False):
        self.count = count
        self.duplicate = duplicate
        self.calls = 0

    def research(self, prompt, *, repair_feedback=None):
        self.calls += 1
        rows = []
        for rank in range(1, self.count + 1):
            ticker = f"T{rank:03d}" if not (self.duplicate and rank == 100) else "T001"
            rows.append(
                {
                    "ticker": ticker,
                    "company_name": f"Company {rank}",
                    "rank": rank,
                    "sector": "Technology",
                    "category": "Infrastructure",
                    "reason": "Qualified theme",
                    "thesis": "Demand growth",
                    "catalysts": ["Capacity"],
                    "risks": ["Valuation"],
                    "confidence": 0.8,
                    "sources": [
                        {
                            "title": "IR",
                            "publisher": "Company",
                            "url": f"https://example.com/{ticker}",
                            "published_at": None,
                        }
                    ],
                    "categories": ["chips_semiconductors"],
                    "feedback_loop_rationale": "Compounds AI infrastructure capacity",
                }
            )
        return rows


def market(count=100):
    tickers = [f"T{i:03d}" for i in range(1, count + 1)]
    return FakeMarketDataProvider(
        pd.DataFrame(
            {
                "Date": [datetime(2026, 8, 17, tzinfo=UTC)] * count,
                "Ticker": tickers,
                "Open": [10] * count,
                "High": [11] * count,
                "Low": [9] * count,
                "Close": [10] * count,
                "Volume": [1000] * count,
            }
        )
    )


def test_exact_100_persistence_reuse_and_force(tmp_path) -> None:
    storage = Storage(tmp_path / "state.db")
    provider = Provider()
    service = UniverseResearchService(storage, market(), provider, "configurable theme")
    first = service.run(period="2026-08")
    assert len(storage.universe_members(first)) == 100
    assert service.run(period="2026-08") == first
    assert provider.calls == 1
    replacement = service.run(period="2026-08", force=True)
    assert replacement != first and provider.calls == 2
    assert storage.active_universe()["id"] == replacement


@pytest.mark.parametrize("count,duplicate", [(99, False), (101, False), (100, True)])
def test_invalid_universes_never_silently_shrink(tmp_path, count, duplicate) -> None:
    service = UniverseResearchService(
        Storage(tmp_path / "state.db"), market(), Provider(count, duplicate), "theme"
    )
    with pytest.raises(ValueError, match="exact valid universe"):
        service.run(period="2026-08", max_attempts=1)


def test_capped_probability_allocation_is_deterministic() -> None:
    policy = CapitalAllocationPolicy(
        threshold=Decimal("0.6"),
        max_positions=2,
        max_position_weight=Decimal("0.5"),
        max_position_notional=Decimal("4000"),
        cash_reserve=Decimal("1000"),
    )
    result = policy.allocate(
        {"AAA": Decimal("0.8"), "BBB": Decimal("0.7"), "LOW": Decimal("0.2")}, Decimal("10000")
    )
    assert [item.ticker for item in result] == ["AAA", "BBB"]
    assert all(item.target_notional <= Decimal("4000") for item in result)
    assert all(item.action == "BUY" for item in result)
