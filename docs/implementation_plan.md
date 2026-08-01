# Implementation Plan

## Scope and safety boundary

This refactor will preserve the existing research workflow while turning the project into an installable, auditable modular monolith for research and paper trading. Paper mode remains the default. No real order will be submitted during implementation or testing. Broker access will be possible only through the execution service; agent output will never bypass deterministic sizing, risk, approval, idempotency, freshness, and kill-switch controls.

Live execution will remain disabled. A disabled live-adapter boundary will expose readiness failures for every required independent gate, including explicit environment flags, adapter capability and enablement, credentials, exact unexpired human approval, deterministic risk approval, idempotency, fresh data, inactive kill switch, an unskipped live test suite, and a visible warning acknowledgement.

## Initial assessment

The stock repository is an early script-based prototype. Useful behavior to preserve includes the 100-symbol thematic universe, adjusted daily OHLCV download, technical features, a label defined as a maximum closing-price gain of at least 10% during the next 50 sessions, chronological validation with a 50-session forward-window embargo, XGBoost, and JSON/CSV/joblib artifacts. Imports depend on the current working directory, generated artifacts are present in the supplied archive, scheduling scripts contain machine-specific paths, and the GitHub workflow attempts to commit a path excluded by `.gitignore`.

The Bank ERP is a small PHP/SQLite application with prepared statements, account management, transactional CSV import, duplicate prevention, and CSRF protection on CSV import. Account create/update/delete mutations lack CSRF protection. Ledger amounts use SQLite `REAL` and PHP floats; the investment integration will therefore store canonical money strings and integer minor units rather than introduce additional binary-float ledger calculations. Existing account and transaction behavior will be preserved.

The workspace contains an incomplete root `.git` directory, so Git status and commit metadata are unavailable. No repository-specific test suite, formatter, linter, or type-check configuration exists.

## Baseline results

- `python -m compileall -q src`: passed.
- `python src/agents/train_xgboost.py --device cpu`: failed before execution because `xgboost` is not installed in the supplied Python environment.
- PHP 8.2.12 lint across all 10 existing PHP files: passed with zero syntax errors.
- `python scripts/init_database.py`: passed and created the ignored local SQLite database.
- PDO SQLite readiness: passed.

## Migration constraints

1. Keep the existing target at a 10% maximum close return over 50 sessions.
2. Keep the chronological evaluation and 50-session embargo.
3. Keep XGBoost as the default production model and retain compatibility wrappers for the current scripts.
4. Keep the current ticker universe file and record deterministic acceptance/rejection separately.
5. Never overwrite historical artifacts; new artifacts will be versioned and integrity hashed.
6. Preserve Bank ERP account and CSV transaction flows while adding an isolated investment integration boundary.
7. Use SQLite for local deterministic runs, with repository interfaces and migrations that do not assume SQLite-only business logic.
8. Use `Decimal` and canonical decimal strings for trading and integration amounts.

## Phased implementation

1. **Foundation:** add packaging, layered typed configuration, versioned Pydantic domain models, identifiers, UTC clock helpers, SQLite migrations, structured redacted logging, audit persistence, and test tooling.
2. **Research and modeling:** wrap the existing downloader, features, target, chronological split, embargo, XGBoost evaluation, registry, promotion state, signals, fixture provider, market-data validation, and leakage audit behind stable package APIs.
3. **News and decisions:** add fixture/RSS provider boundaries, deduplication, prompt-injection-safe structured analysis, evidence validation, conservative decision policy, and deterministic abstention.
4. **Risk and paper execution:** add deterministic sizing and machine-readable risk checks, immutable exact-order approvals, kill switch, fake broker state machine, durable idempotent submission, reconciliation, and immutable portfolio ledger events.
5. **ERP boundary:** add a versioned JSON Schema in both repositories, canonical batch hashing, filesystem transport, export history, transactional PHP CLI importer, source-event uniqueness, idempotent batch handling, audit records, and an investment report.
6. **Operations:** add explicit orchestration, resumable stage records, CLI workflows, health output, metrics, alerts, configuration examples, CI, and runbooks.
7. **Quality and documentation:** add unit, integration, contract, regression, and deterministic end-to-end tests; run formatting, lint, typing, coverage, PHP lint, schema checks, and the fixture demo; document exact results and limitations.

## Verification targets

- Installation and configuration validation succeed without secrets.
- Existing label and embargo regression tests pass.
- A fixture model is trained, evaluated, explicitly approved, integrity checked, and used for signals.
- Fixture news produces evidence-linked assessments.
- A recommendation flows through deterministic sizing, risk, paper approval, fake-broker execution, reconciliation, portfolio accounting, ERP export, and idempotent ERP re-import.
- The kill switch and all attempted live-gate bypasses fail closed.
- Logs redact secrets and carry run/correlation identifiers.
- Health reports live readiness as false by default.
- No test or command contacts a real broker or submits a real order.
