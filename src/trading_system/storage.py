"""SQLite persistence for research, simulation, accounting, and audit state."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .clock import utc_now

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS records (
  record_type TEXT NOT NULL, record_id TEXT NOT NULL, run_id TEXT NOT NULL,
  status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (record_type, record_id)
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
  idempotency_key TEXT PRIMARY KEY, order_intent_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kill_switch (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1), active INTEGER NOT NULL,
  reason TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT OR IGNORE INTO kill_switch(singleton, active, reason, updated_at)
VALUES (1, 0, '', CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS run_locks (
  lock_name TEXT PRIMARY KEY, run_id TEXT NOT NULL, acquired_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_runs (
  id TEXT PRIMARY KEY, run_type TEXT NOT NULL, market_session TEXT,
  universe_run_id TEXT, status TEXT NOT NULL, started_at TEXT NOT NULL,
  completed_at TEXT, summary_json TEXT NOT NULL DEFAULT '{}', error_message TEXT,
  UNIQUE(run_type, market_session)
);
CREATE TABLE IF NOT EXISTS universe_runs (
  id TEXT PRIMARY KEY, period TEXT NOT NULL UNIQUE, strategy_id TEXT NOT NULL,
  created_at TEXT NOT NULL, llm_provider TEXT NOT NULL, llm_model TEXT NOT NULL,
  prompt_version TEXT NOT NULL, status TEXT NOT NULL, github_job_id TEXT
);
CREATE TABLE IF NOT EXISTS universe_members (
  universe_run_id TEXT NOT NULL, ticker TEXT NOT NULL, company_name TEXT NOT NULL,
  rank INTEGER NOT NULL, sector TEXT NOT NULL, category TEXT NOT NULL,
  reason TEXT NOT NULL, thesis TEXT NOT NULL, catalysts_json TEXT NOT NULL,
  risks_json TEXT NOT NULL, confidence TEXT, researched_at TEXT NOT NULL,
  ai_infra_categories_json TEXT NOT NULL DEFAULT '[]',
  feedback_loop_rationale TEXT,
  PRIMARY KEY(universe_run_id, ticker), UNIQUE(universe_run_id, rank),
  FOREIGN KEY(universe_run_id) REFERENCES universe_runs(id)
);
CREATE TABLE IF NOT EXISTS research_sources (
  id TEXT PRIMARY KEY, universe_run_id TEXT NOT NULL, ticker TEXT NOT NULL,
  title TEXT NOT NULL, publisher TEXT NOT NULL, url TEXT NOT NULL,
  published_at TEXT, retrieved_at TEXT NOT NULL,
  UNIQUE(universe_run_id, ticker, url),
  FOREIGN KEY(universe_run_id) REFERENCES universe_runs(id)
);
CREATE TABLE IF NOT EXISTS model_signals (
  id TEXT PRIMARY KEY, strategy_run_id TEXT NOT NULL, universe_run_id TEXT NOT NULL,
  ticker TEXT NOT NULL, model_version TEXT NOT NULL, probability TEXT NOT NULL,
  rank INTEGER NOT NULL, market_session TEXT NOT NULL, reference_price TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(strategy_run_id, ticker)
);
CREATE TABLE IF NOT EXISTS capital_allocations (
  id TEXT PRIMARY KEY, strategy_run_id TEXT NOT NULL, ticker TEXT NOT NULL,
  target_notional TEXT NOT NULL, target_weight TEXT NOT NULL,
  current_notional TEXT NOT NULL, current_weight TEXT NOT NULL,
  allocation_action TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(strategy_run_id, ticker)
);
CREATE TABLE IF NOT EXISTS trade_decisions (
  id TEXT PRIMARY KEY, strategy_run_id TEXT NOT NULL, universe_run_id TEXT NOT NULL,
  market_session TEXT NOT NULL, ticker TEXT NOT NULL, decision_type TEXT NOT NULL,
  reason TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS simulated_trades (
  id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE, strategy_run_id TEXT NOT NULL,
  universe_run_id TEXT NOT NULL, ticker TEXT NOT NULL, executed_at TEXT NOT NULL,
  market_session TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL,
  price TEXT NOT NULL, notional TEXT NOT NULL, fees TEXT NOT NULL,
  realized_pnl TEXT NOT NULL, portfolio_value_before TEXT NOT NULL,
  portfolio_value_after TEXT NOT NULL, reason TEXT NOT NULL,
  market_data_timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), cash TEXT NOT NULL,
  starting_capital TEXT NOT NULL, realized_pnl TEXT NOT NULL,
  portfolio_peak TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
  ticker TEXT PRIMARY KEY, quantity TEXT NOT NULL, average_cost TEXT NOT NULL,
  opened_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  id TEXT PRIMARY KEY, strategy_run_id TEXT NOT NULL, market_session TEXT NOT NULL UNIQUE,
  cash TEXT NOT NULL, invested_value TEXT NOT NULL, total_value TEXT NOT NULL,
  realized_pnl TEXT NOT NULL, unrealized_pnl TEXT NOT NULL, daily_pnl TEXT NOT NULL,
  daily_return TEXT NOT NULL, cumulative_return TEXT NOT NULL, positions_count INTEGER NOT NULL,
  portfolio_peak TEXT NOT NULL, drawdown TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmark_snapshots (
  id TEXT PRIMARY KEY, strategy_run_id TEXT NOT NULL, market_session TEXT NOT NULL,
  ticker TEXT NOT NULL, price TEXT NOT NULL, cumulative_return TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(market_session, ticker)
);
"""


class Storage:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._ensure_universe_member_columns()

    def close(self) -> None:
        self.connection.close()

    def _ensure_universe_member_columns(self) -> None:
        columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(universe_members)")
        }
        if "ai_infra_categories_json" not in columns:
            self.connection.execute(
                "ALTER TABLE universe_members "
                "ADD COLUMN ai_infra_categories_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "feedback_loop_rationale" not in columns:
            self.connection.execute(
                "ALTER TABLE universe_members ADD COLUMN feedback_loop_rationale TEXT"
            )
        self.connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def save(
        self, record_type: str, record_id: str, run_id: str, status: str, payload: Any
    ) -> None:
        serialized = (
            payload.model_dump_json()
            if hasattr(payload, "model_dump_json")
            else json.dumps(payload, default=str)
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?, ?, ?)",
            (record_type, record_id, run_id, status, serialized, utc_now().isoformat()),
        )
        self.connection.commit()

    def load(self, record_type: str, record_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT payload FROM records WHERE record_type=? AND record_id=?",
            (record_type, record_id),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def reserve_idempotency_key(self, key: str, intent_id: str) -> bool:
        try:
            self.connection.execute(
                "INSERT INTO idempotency_keys VALUES (?, ?, ?)",
                (key, intent_id, utc_now().isoformat()),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def kill_switch_active(self) -> bool:
        row = self.connection.execute("SELECT active FROM kill_switch WHERE singleton=1").fetchone()
        return bool(row["active"])

    def set_kill_switch(self, active: bool, reason: str) -> None:
        self.connection.execute(
            "UPDATE kill_switch SET active=?, reason=?, updated_at=? WHERE singleton=1",
            (int(active), reason, utc_now().isoformat()),
        )
        self.connection.commit()

    def acquire_lock(self, name: str, run_id: str) -> None:
        self.connection.execute(
            "INSERT INTO run_locks VALUES (?, ?, ?)", (name, run_id, utc_now().isoformat())
        )
        self.connection.commit()

    def release_lock(self, name: str, run_id: str) -> None:
        self.connection.execute(
            "DELETE FROM run_locks WHERE lock_name=? AND run_id=?", (name, run_id)
        )
        self.connection.commit()

    def initialize_portfolio(self, capital: str) -> None:
        now = utc_now().isoformat()
        self.connection.execute(
            "INSERT OR IGNORE INTO portfolio_state VALUES (1, ?, ?, '0', ?, ?)",
            (capital, capital, capital, now),
        )
        self.connection.commit()

    def row(self, sql: str, values: tuple[object, ...] = ()) -> dict[str, Any] | None:
        result = self.connection.execute(sql, values).fetchone()
        return dict(result) if result else None

    def rows(self, sql: str, values: tuple[object, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(sql, values).fetchall()]

    def execute(self, sql: str, values: tuple[object, ...] = ()) -> None:
        self.connection.execute(sql, values)
        self.connection.commit()

    def active_universe(self) -> dict[str, Any] | None:
        return self.row(
            "SELECT * FROM universe_runs WHERE status='completed' ORDER BY period DESC LIMIT 1"
        )

    def universe_members(self, run_id: str) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM universe_members WHERE universe_run_id=? ORDER BY rank", (run_id,)
        )

    def last_completed_session(self) -> str | None:
        row = self.row(
            "SELECT market_session FROM strategy_runs WHERE run_type='eod' AND status='completed' "
            "ORDER BY market_session DESC LIMIT 1"
        )
        return str(row["market_session"]) if row else None
