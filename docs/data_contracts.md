# Data Contracts

`trading_system.types` defines strict, frozen, extra-forbidden Pydantic contracts for all material records: ticker proposals/decisions; market bars/snapshots; feature and training manifests; model metadata/evaluations/signals; articles/evidence/assessments; accounts/positions/portfolios; recommendations/risk checks; order intents/approvals/requests/orders; reports/fills/reconciliation; agent decisions/runs; pipeline/audit records; and ERP batches/results.

Records use schema version `1.0.0`, opaque immutable IDs, run/correlation/causation IDs, UTC-aware timestamps, producer/source/status fields, validation errors, and provenance where relevant. Naive datetimes are rejected. Money and quantities use `Decimal`. Enums constrain finite directions, actions, risk outcomes, and order states.

The ERP JSON Schema is `contracts/investment_export_v1.schema.json` in both repositories. Batch integrity covers version, ID, source, account, and complete events. Each event has its own content hash. Optional HMAC uses an environment-only shared secret. Re-import uniqueness is `(source_system, event_external_id)` and `batch_id`.

