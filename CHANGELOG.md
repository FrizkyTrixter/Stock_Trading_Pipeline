# Changelog

## 0.1.0 - 2026-08-01

- Preserved the 10%/50-session target, 50-session embargo, technical features, XGBoost, universe, and legacy entry points.
- Replaced the obsolete fake/live adapter architecture with Yahoo-priced simulated execution, deterministic allocation and stops, durable daily idempotency, and normalized ERP strategy events.
- Added a matching transactional and idempotent Bank ERP investment importer and read-only report.
- Added CSRF protection to Bank ERP account create/update/delete operations.
- Added unit, integration, contract, safety, and fixture end-to-end tests.
- Changed the market-data workflow so generated parquet data is an uploaded CI artifact rather than a repository commit.
