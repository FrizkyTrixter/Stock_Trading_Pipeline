# Testing Strategy

Unit tests cover configuration contradictions, timezone/Decimal schemas, secret redaction, prompt injection, hashing, storage idempotency/locks/kill switch, universe restrictions, target/embargo regression, leakage audit, news deduplication/evidence IDs, sizing/risk, exact approvals, live gates, duplicate submission, staleness, expiry, timeout ambiguity, and disabled live execution.

Integration/end-to-end tests use generated OHLCV, deterministic XGBoost, fixture news, deterministic analysis, temporary SQLite, fake broker, portfolio ledger, filesystem ERP transport, temporary Bank ERP database, and PHP CLI importer. They verify full fill, reconciliation, export, first import, and duplicate re-import. No test requires secrets, network, a paid provider, or a broker.

Coverage minimum is 75%. CI runs format, lint, strict typing, tests/coverage, and compilation. PHP lint and the cross-repo importer test must also pass locally. External adapters should add replay tests for timeout, rate limit, malformed content, partial fill, stale status, and provider terms.
