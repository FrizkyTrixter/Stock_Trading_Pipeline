.PHONY: install format lint type test fixture health

install:
	python -m pip install -e ".[dev,market-data,research]"

format:
	ruff format src tests

lint:
	ruff format --check src tests
	ruff check src tests

type:
	mypy src/trading_system

test:
	pytest -q

fixture:
	trading-system run daily --fixture --workspace artifacts/runs/fixture-daily

health:
	trading-system health

