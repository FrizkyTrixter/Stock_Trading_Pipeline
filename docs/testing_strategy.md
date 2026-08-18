# Testing

Tests inject Yahoo downloaders, fixed signal services, and fixture research providers. They cover
normalization, batching/retries, exact-100 rules, duplicate rejection, monthly reuse/force, allocation,
buy/sell/P&L, stops, authoritative snapshots, EOD idempotency, backtest timing, feature leakage, and
signed ERP output. Bank ERP’s CLI suite covers job persistence, duplicate prevention, workflow
dispatch construction, server-only token handling, CSRF, migrations, and existing banking tables.

```powershell
python -m pytest -q
python -m ruff check src tests
python -m mypy src/trading_system
php scripts/test.php
```
