# Paper Trading

`FakeBrokerAdapter` supports full fills, partial fills, rejection, deterministic timeout/ambiguity, and duplicate idempotency behavior. It advertises no live capability. Paper orders default to limit orders. `ExecutionService` persists submission intent before the external boundary, reserves the idempotency key, and persists broker orders/fills after success.

An ambiguous timeout is not retried: the intent is marked reconciliation-required. Reconciliation compares local and broker order IDs, states, and filled quantities, and reports broker-only/local-only/status/quantity discrepancies without silently changing the ledger. `PortfolioLedger` creates immutable fill events and rejects a duplicate fill source ID.

Run `trading-system run daily --fixture --workspace artifacts/runs/fixture-daily` for the deterministic demonstration.

