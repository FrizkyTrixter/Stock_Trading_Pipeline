# Threat Model

Protected assets include credentials, approvals, idempotency keys, model/data artifacts, broker state, ledger events, ERP batches, personal account data, and audit history.

| Threat | Primary controls | Residual risk/action |
|---|---|---|
| Leaked keys/tokens/log data | environment secrets, `.gitignore`, redaction, no credentials in ERP | rotate and inspect history |
| Malicious news/prompt injection | untrusted-data rule, pattern screening, strict schema, evidence IDs, no tools | production LLM adapter needs adversarial review |
| Dependency compromise/confusion | bounded dependencies, package name, CI checks | add lockfile/SBOM/scanner |
| Manipulated/stale market data | provider provenance, hashes, OHLC validation, freshness gates | qualified second source pending |
| Duplicate/ambiguous orders | durable intent, unique idempotency, no blind retry, reconciliation | broker-specific semantics pending |
| Replayed/changed approval | exact intent hash, environment binding, expiry, immutable record | identity provider pending |
| Tampered ERP batch | event/batch SHA-256, optional HMAC, transaction, uniqueness | authenticated HTTP pending |
| Unauthorized live activation | independent gates, disabled adapter, false health, kill switch, tests | live implementation absent |
| SQL injection | PDO prepared statements; fixed SQL in Python | keep dynamic filters parameterized |
| CSRF | session tokens on import and account mutations | add secure cookie/header policy in deployment |
| Dependency or subprocess abuse | fixed argv, no shell interpolation, least-privilege adapters | sandbox provider tools |

