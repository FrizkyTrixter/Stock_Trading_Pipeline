# Contributing

Use Python 3.11 or newer, install `.[dev,market-data,research]`, and keep changes small and test-backed. Do not alter the target, horizon, embargo, thresholds, or metric meanings without a migration note, changelog entry, and regression tests.

Before proposing a change, run:

```powershell
ruff format --check src tests
ruff check src tests
mypy src/trading_system
pytest -q
python -m compileall -q src
```

Run PHP lint in the Bank ERP repository. Tests must use fixtures, fake adapters, temporary databases, and no paid credentials or real orders.

