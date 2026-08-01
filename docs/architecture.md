# Architecture

The system is a modular monolith with dependency inversion at market data, news, model artifact, broker, alert, and ERP transport boundaries. `Orchestrator` owns the visible stage sequence and durable stage status. Pydantic records are the boundary types; `Storage` persists JSON records and execution invariants in SQLite.

Probabilistic components may propose a universe or interpret retrieved text. Deterministic components validate universes, market bars, features, splits, labels, evidence IDs, configurations, model integrity and approval, decisions thresholds, sizing, risk, approvals, execution, reconciliation, portfolio events, ERP hashing, and audit persistence.

The daily fixture sequence is market validation, features/leakage audit, train/evaluate, explicit model approval, signals, news collect/analyze, portfolio snapshot, recommendation, sizing/risk, approval, fake execution, reconciliation, portfolio update, ERP export, and run report. A run lock prevents concurrent daily ownership. Stages record running/completed/failed status and duration; retry policy belongs only at idempotent external adapters.

Large market datasets remain parquet artifacts. Transactional state and metadata live in SQLite locally. PostgreSQL support should replace the repository layer without changing domain contracts.

