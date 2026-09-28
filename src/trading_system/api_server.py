"""Read-only FastAPI surface over the simulated-trading ledger.

External agents and dashboards (for example the Bank ERP "Agentic Trading"
page) use this API to observe the pipeline without touching it.

Safety properties
-----------------
* The SQLite database is opened with ``mode=ro`` via a URI, so the server
  process can never write to the ledger -- not even by accident.
* Every route is a ``GET``; there are no trading, order-placement, or
  mutation endpoints anywhere in this module.
* Money values are serialized as strings (the pipeline stores ``Decimal``
  values as text) and timestamps are ISO-8601 strings.
* The database path comes from the ``TRADING_DATABASE_PATH`` environment
  variable and defaults to ``data/trading_system.db``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import __version__

#: Database location used when TRADING_DATABASE_PATH is not set.
DEFAULT_DATABASE_PATH = Path("data/trading_system.db")

#: Hard upper bound for ``?limit=`` pagination parameters.
MAX_LIMIT = 500

#: decision_type -> trade side mapping for the decisions endpoint.
_DECISION_SIDE = {
    "MODEL_ENTRY": "BUY",
    "STOP_LOSS_EXIT": "SELL",
    "UNIVERSE_REMOVAL": "SELL",
}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: str
    version: str


class PortfolioResponse(BaseModel):
    """Aggregate simulated-portfolio state."""

    cash: str
    starting_capital: str
    realized_pnl: str
    portfolio_peak: str
    position_count: int


class PositionResponse(BaseModel):
    """A single open simulated position."""

    ticker: str
    quantity: str
    average_cost: str


class TradeResponse(BaseModel):
    """A simulated execution enriched with its AI decision context."""

    id: str
    ticker: str
    side: str
    quantity: str
    price: str
    notional: str
    fees: str
    realized_pnl: str
    portfolio_value_before: str
    portfolio_value_after: str
    reason: str
    market_data_timestamp: str
    decision_confidence: str | None = None
    decision_rationale: str | None = None
    decision_metadata: dict[str, Any] = {}


class DecisionResponse(BaseModel):
    """A recorded trade decision (recommendation outcome)."""

    id: str
    ticker: str
    side: str
    reason: str
    confidence: str | None = None
    rationale: str | None = None
    metadata: dict[str, Any] = {}
    created_at: str


class UniverseMemberResponse(BaseModel):
    """One member of the latest researched universe."""

    ticker: str
    company_name: str
    rank: int
    sector: str
    category: str
    reason: str
    thesis: str
    catalysts: list[str] = []
    risks: list[str] = []
    confidence: str | None = None
    feedback_loop_rationale: str | None = None


# ---------------------------------------------------------------------------
# Read-only database access
# ---------------------------------------------------------------------------


def database_path() -> Path:
    """Resolve the ledger database path (re-read per request for tests)."""
    return Path(os.environ.get("TRADING_DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))


@contextmanager
def readonly_connection() -> Iterator[sqlite3.Connection]:
    """Yield a read-only SQLite connection to the trading ledger.

    ``mode=ro`` makes the open fail when the file is missing and guarantees
    the server can never create, lock, or modify the database.
    """
    uri = f"file:{database_path().absolute()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=503, detail=f"Trading database unavailable: {exc}"
        ) from exc
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def get_connection() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency providing a per-request read-only connection."""
    with readonly_connection() as connection:
        yield connection


def _parse_json_object(raw: Any) -> dict[str, Any]:
    """Parse a JSON object column, tolerating NULL/invalid payloads."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_list(raw: Any) -> list[str]:
    """Parse a JSON array column into a list of strings."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _money(value: Any) -> str:
    """Serialize a stored Decimal-as-text money field."""
    return str(value) if value is not None else "0"


def _text(value: Any) -> str | None:
    """Serialize an optional free-text field without pydantic coercion."""
    return None if value is None else str(value)


def _decision_side(decision_type: str, metadata: dict[str, Any]) -> str:
    """Best-effort trade side for a decision record.

    The recording layer may stash an explicit ``side`` in the decision
    metadata; otherwise the side is derived from the decision type.
    """
    explicit = metadata.get("side")
    if isinstance(explicit, str) and explicit:
        return explicit.upper()
    return _DECISION_SIDE.get(decision_type, decision_type)


def _decision_response(row: sqlite3.Row) -> DecisionResponse:
    """Build a DecisionResponse from a trade_decisions row."""
    metadata = _parse_json_object(row["metadata_json"])
    return DecisionResponse(
        id=row["id"],
        ticker=row["ticker"],
        side=_decision_side(row["decision_type"], metadata),
        reason=row["reason"],
        confidence=_text(metadata.get("confidence")),
        rationale=_text(metadata.get("rationale")),
        metadata=metadata,
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Trading System Read-Only API",
    description=(
        "Read-only JSON surface over the simulated-trading ledger. "
        "No endpoint can trade, mutate, or persist state."
    ),
    version=__version__,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok", version=__version__)


@app.get("/api/portfolio", response_model=PortfolioResponse)
def get_portfolio(
    connection: sqlite3.Connection = Depends(get_connection),
) -> PortfolioResponse:
    """Aggregate cash, capital, realized P&L, peak value, and position count."""
    row = connection.execute(
        "SELECT cash, starting_capital, realized_pnl, portfolio_peak "
        "FROM portfolio_state WHERE singleton = 1"
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Portfolio state not initialized")
    position_count = connection.execute("SELECT COUNT(*) AS n FROM positions").fetchone()
    return PortfolioResponse(
        cash=_money(row["cash"]),
        starting_capital=_money(row["starting_capital"]),
        realized_pnl=_money(row["realized_pnl"]),
        portfolio_peak=_money(row["portfolio_peak"]),
        position_count=int(position_count["n"]),
    )


@app.get("/api/positions", response_model=list[PositionResponse])
def get_positions(
    connection: sqlite3.Connection = Depends(get_connection),
) -> list[PositionResponse]:
    """Currently open simulated positions."""
    rows = connection.execute(
        "SELECT ticker, quantity, average_cost FROM positions ORDER BY ticker"
    ).fetchall()
    return [
        PositionResponse(
            ticker=row["ticker"],
            quantity=_money(row["quantity"]),
            average_cost=_money(row["average_cost"]),
        )
        for row in rows
    ]


@app.get("/api/trades", response_model=list[TradeResponse])
def get_trades(
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    connection: sqlite3.Connection = Depends(get_connection),
) -> list[TradeResponse]:
    """Recent simulated trades, newest first, with AI decision context."""
    rows = connection.execute(
        """
        SELECT t.*, d.metadata_json AS decision_metadata_json
        FROM simulated_trades AS t
        LEFT JOIN trade_decisions AS d ON d.id = t.decision_id
        ORDER BY t.executed_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    trades: list[TradeResponse] = []
    for row in rows:
        metadata = _parse_json_object(row["decision_metadata_json"])
        trades.append(
            TradeResponse(
                id=row["id"],
                ticker=row["ticker"],
                side=row["side"],
                quantity=_money(row["quantity"]),
                price=_money(row["price"]),
                notional=_money(row["notional"]),
                fees=_money(row["fees"]),
                realized_pnl=_money(row["realized_pnl"]),
                portfolio_value_before=_money(row["portfolio_value_before"]),
                portfolio_value_after=_money(row["portfolio_value_after"]),
                reason=row["reason"],
                market_data_timestamp=row["market_data_timestamp"],
                decision_confidence=_text(metadata.get("confidence")),
                decision_rationale=_text(metadata.get("rationale")),
                decision_metadata=metadata,
            )
        )
    return trades


@app.get("/api/decisions", response_model=list[DecisionResponse])
def get_decisions(
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    connection: sqlite3.Connection = Depends(get_connection),
) -> list[DecisionResponse]:
    """Recent trade decisions, newest first."""
    rows = connection.execute(
        "SELECT * FROM trade_decisions ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_decision_response(row) for row in rows]


@app.get("/api/universe", response_model=list[UniverseMemberResponse])
def get_universe(
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
    connection: sqlite3.Connection = Depends(get_connection),
) -> list[UniverseMemberResponse]:
    """Members of the latest research universe, ranked."""
    run = connection.execute(
        "SELECT id FROM universe_runs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if run is None:
        raise HTTPException(status_code=404, detail="No universe runs recorded")
    rows = connection.execute(
        "SELECT * FROM universe_members WHERE universe_run_id = ? ORDER BY rank LIMIT ?",
        (run["id"], limit),
    ).fetchall()
    return [
        UniverseMemberResponse(
            ticker=row["ticker"],
            company_name=row["company_name"],
            rank=int(row["rank"]),
            sector=row["sector"],
            category=row["category"],
            reason=row["reason"],
            thesis=row["thesis"],
            catalysts=_parse_json_list(row["catalysts_json"]),
            risks=_parse_json_list(row["risks_json"]),
            confidence=_text(row["confidence"]),
            feedback_loop_rationale=_text(row["feedback_loop_rationale"]),
        )
        for row in rows
    ]
