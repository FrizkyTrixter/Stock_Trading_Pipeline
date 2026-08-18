# ADR 0003: SQLite local storage

Status: accepted, 2026-08-01.

Use SQLite for local paper mode and tests, parquet for large market datasets, and JSON/joblib for versioned artifacts. SQLite provides transactions, uniqueness, and simple operations. Repository boundaries and portable contracts keep PostgreSQL feasible; SQLite-specific business rules are avoided.

