"""SQLite persistence for runs, audit events, approvals, orders, and export history."""

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
"""


class Storage:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

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
