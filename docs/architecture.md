# Architecture

The installable `trading_system` package is a modular monolith. `research.py` owns the LLM boundary;
`market_data.py` owns all Yahoo access; `features.py`, `modeling.py`, and `signals.py` own leakage-safe
XGBoost work; `allocation.py` owns deterministic sizing; `simulation.py` owns the only execution and
portfolio-accounting path; `daily.py` owns market-session orchestration; and `erp_integration.py`
owns the signed external boundary. SQLite enforces session, decision, trade, and snapshot uniqueness.

Bank ERP does not share this database. It triggers GitHub Actions through its backend and accepts
only canonical HMAC-signed batches at its ingestion endpoint.
