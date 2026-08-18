# Architecture inventory and disposition

| Existing module | Current purpose | Decision | Target responsibility |
|---|---|---|---|
| `types.py`, `storage.py`, `security.py` | Contracts, SQLite, integrity | Modify | Strategy lineage, simulation state, idempotency |
| `features.py`, `modeling.py`, `train_xgboost.py` | Leakage-aware XGBoost | Keep/modify | Score the active versioned universe |
| `market_data.py`, legacy downloader | Parquet plus scattered Yahoo calls | Consolidate | One batched Yahoo service |
| fake/live execution modules | Test broker and disabled live gates | Delete | Replaced by `SimulatedExecutionEngine` |
| legacy research agent | Standalone two-call script | Replace | Monthly versioned `UniverseResearchService` |
| ERP exporter/schema | Signed basic investment events | Extend | Normalized strategy event contract |
| fixture orchestration/CLI | Demo workflow | Replace | Research, market update, and EOD commands |
| ERP importer/events page | HMAC import and read-only list | Extend | Strategy tables, dispatch, dashboard, research, picks, journal |

The inspected ERP baseline tables were `accounts`, `transactions`,
`investment_account_mappings`, `investment_import_batches`, `investment_events`, and
`investment_audit_log`. Existing banking data and pages remain additive and untouched.
