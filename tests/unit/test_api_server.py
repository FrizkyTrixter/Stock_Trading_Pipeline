"""Unit tests for the read-only trading API.

The API is exercised with fastapi.testclient.TestClient against a temporary
SQLite database with a minimal ledger schema. The real database is never
touched, and the tests assert the server cannot modify the fixture file.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trading_system import __version__, api_server

SCHEMA = """
CREATE TABLE portfolio_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), cash TEXT NOT NULL,
  starting_capital TEXT NOT NULL, realized_pnl TEXT NOT NULL,
  portfolio_peak TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE positions (
  ticker TEXT PRIMARY KEY, quantity TEXT NOT NULL, average_cost TEXT NOT NULL,
  opened_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE trade_decisions (
  id TEXT PRIMARY KEY, strategy_run_id TEXT NOT NULL, universe_run_id TEXT NOT NULL,
  market_session TEXT NOT NULL, ticker TEXT NOT NULL, decision_type TEXT NOT NULL,
  reason TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE simulated_trades (
  id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE, strategy_run_id TEXT NOT NULL,
  universe_run_id TEXT NOT NULL, ticker TEXT NOT NULL, executed_at TEXT NOT NULL,
  market_session TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL,
  price TEXT NOT NULL, notional TEXT NOT NULL, fees TEXT NOT NULL,
  realized_pnl TEXT NOT NULL, portfolio_value_before TEXT NOT NULL,
  portfolio_value_after TEXT NOT NULL, reason TEXT NOT NULL,
  market_data_timestamp TEXT NOT NULL
);
CREATE TABLE universe_runs (
  id TEXT PRIMARY KEY, period TEXT NOT NULL UNIQUE, strategy_id TEXT NOT NULL,
  created_at TEXT NOT NULL, llm_provider TEXT NOT NULL, llm_model TEXT NOT NULL,
  prompt_version TEXT NOT NULL, status TEXT NOT NULL, github_job_id TEXT
);
CREATE TABLE universe_members (
  universe_run_id TEXT NOT NULL, ticker TEXT NOT NULL, company_name TEXT NOT NULL,
  rank INTEGER NOT NULL, sector TEXT NOT NULL, category TEXT NOT NULL,
  reason TEXT NOT NULL, thesis TEXT NOT NULL, catalysts_json TEXT NOT NULL,
  risks_json TEXT NOT NULL, confidence TEXT, researched_at TEXT NOT NULL,
  ai_infra_categories_json TEXT NOT NULL DEFAULT '[]',
  feedback_loop_rationale TEXT,
  PRIMARY KEY(universe_run_id, ticker), UNIQUE(universe_run_id, rank)
);
"""

NOW = "2026-09-25T20:00:00+00:00"


def _seed(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO portfolio_state VALUES (1, ?, ?, ?, ?, ?)",
        ("95000.00", "100000.00", "-5000.00", "102000.00", NOW),
    )
    connection.executemany(
        "INSERT INTO positions VALUES (?, ?, ?, ?, ?)",
        [
            ("AAPL", "10", "150.00", NOW, NOW),
            ("MSFT", "5", "300.00", NOW, NOW),
        ],
    )
    connection.execute(
        "INSERT INTO trade_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "decision_1",
            "strategy_1",
            "universe_1",
            "2026-09-25",
            "AAPL",
            "MODEL_ENTRY",
            "Model entry signal",
            json.dumps({"confidence": "0.82", "rationale": "Strong momentum"}),
            NOW,
            "strategy_1:2026-09-25:AAPL:MODEL_ENTRY",
        ),
    )
    connection.execute(
        "INSERT INTO trade_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "decision_2",
            "strategy_1",
            "universe_1",
            "2026-09-24",
            "MSFT",
            "STOP_LOSS_EXIT",
            "Stop loss breached",
            json.dumps({"confidence": "0.91", "rationale": "Capital preservation"}),
            "2026-09-24T20:00:00+00:00",
            "strategy_1:2026-09-24:MSFT:STOP_LOSS_EXIT",
        ),
    )
    connection.execute(
        "INSERT INTO simulated_trades VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "execution_1",
            "decision_1",
            "strategy_1",
            "universe_1",
            "AAPL",
            NOW,
            "2026-09-25",
            "BUY",
            "10",
            "150.00",
            "1500.00",
            "1.00",
            "0",
            "100000.00",
            "99999.00",
            "Model entry signal",
            "2026-09-25T16:00:00+00:00",
        ),
    )
    connection.execute(
        "INSERT INTO universe_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "universe_1",
            "2026-09",
            "strategy_1",
            "2026-09-01T00:00:00+00:00",
            "openai",
            "gpt-5",
            "v1",
            "completed",
            None,
        ),
    )
    connection.execute(
        "INSERT INTO universe_members VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "universe_1",
            "AAPL",
            "Apple Inc.",
            1,
            "Technology",
            "mega-cap",
            "Index leader",
            "Durable cash flows fund AI capex",
            json.dumps(["iPhone cycle", "Services growth"]),
            json.dumps(["Valuation", "China exposure"]),
            "0.9",
            "2026-09-01T00:00:00+00:00",
            json.dumps(["ai-infra"]),
            "AI capex demand supports the thesis",
        ),
    )
    connection.commit()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "test_trading.db"
    connection = sqlite3.connect(str(db_path))
    _seed(connection)
    connection.close()
    monkeypatch.setenv("TRADING_DATABASE_PATH", str(db_path))
    return TestClient(api_server.app)


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_portfolio(client: TestClient) -> None:
    body = client.get("/api/portfolio").json()
    assert body == {
        "cash": "95000.00",
        "starting_capital": "100000.00",
        "realized_pnl": "-5000.00",
        "portfolio_peak": "102000.00",
        "position_count": 2,
    }


def test_positions(client: TestClient) -> None:
    body = client.get("/api/positions").json()
    assert body == [
        {"ticker": "AAPL", "quantity": "10", "average_cost": "150.00"},
        {"ticker": "MSFT", "quantity": "5", "average_cost": "300.00"},
    ]


def test_trades_join_decision_context(client: TestClient) -> None:
    body = client.get("/api/trades").json()
    assert len(body) == 1
    trade = body[0]
    assert trade["id"] == "execution_1"
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "BUY"
    assert trade["quantity"] == "10"
    assert trade["price"] == "150.00"
    assert trade["notional"] == "1500.00"
    assert trade["fees"] == "1.00"
    assert trade["realized_pnl"] == "0"
    assert trade["portfolio_value_before"] == "100000.00"
    assert trade["portfolio_value_after"] == "99999.00"
    assert trade["reason"] == "Model entry signal"
    assert trade["market_data_timestamp"] == "2026-09-25T16:00:00+00:00"
    assert trade["decision_confidence"] == "0.82"
    assert trade["decision_rationale"] == "Strong momentum"
    assert trade["decision_metadata"] == {
        "confidence": "0.82",
        "rationale": "Strong momentum",
    }


def test_trades_limit_parameter(client: TestClient) -> None:
    assert client.get("/api/trades", params={"limit": 1}).json() != []
    assert client.get("/api/trades", params={"limit": 0}).status_code == 422


def test_decisions_newest_first_with_side(client: TestClient) -> None:
    body = client.get("/api/decisions").json()
    assert [item["id"] for item in body] == ["decision_1", "decision_2"]
    first = body[0]
    assert first["ticker"] == "AAPL"
    assert first["side"] == "BUY"
    assert first["reason"] == "Model entry signal"
    assert first["confidence"] == "0.82"
    assert first["rationale"] == "Strong momentum"
    assert first["metadata"] == {"confidence": "0.82", "rationale": "Strong momentum"}
    assert first["created_at"] == NOW
    assert body[1]["side"] == "SELL"


def test_universe_latest_run_members(client: TestClient) -> None:
    body = client.get("/api/universe").json()
    assert len(body) == 1
    member = body[0]
    assert member["ticker"] == "AAPL"
    assert member["company_name"] == "Apple Inc."
    assert member["rank"] == 1
    assert member["sector"] == "Technology"
    assert member["category"] == "mega-cap"
    assert member["thesis"] == "Durable cash flows fund AI capex"
    assert member["catalysts"] == ["iPhone cycle", "Services growth"]
    assert member["risks"] == ["Valuation", "China exposure"]
    assert member["confidence"] == "0.9"
    assert member["feedback_loop_rationale"] == "AI capex demand supports the thesis"


def test_api_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "readonly_check.db"
    connection = sqlite3.connect(str(db_path))
    _seed(connection)
    connection.close()
    monkeypatch.setenv("TRADING_DATABASE_PATH", str(db_path))
    before = _checksum(db_path)
    api_client = TestClient(api_server.app)
    for path in ("/api/portfolio", "/api/positions", "/api/trades", "/api/decisions",
                 "/api/universe"):
        assert api_client.get(path).status_code == 200
    # No mutation routes exist: writes are rejected with 405.
    assert api_client.post("/api/trades").status_code == 405
    assert api_client.delete("/api/positions").status_code == 405
    assert _checksum(db_path) == before


def test_missing_database_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_DATABASE_PATH", "/nonexistent-dir/trading.db")
    response = TestClient(api_server.app).get("/api/portfolio")
    assert response.status_code == 503
