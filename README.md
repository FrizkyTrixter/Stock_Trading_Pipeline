# AI-Driven Adaptive Trading System

This repository is an early research prototype for an adaptive stock-trading
system. The current milestone is deliberately limited to an auditable machine
learning research loop: market data in, chronological model evaluation, and
ranked candidates out. It does **not** place trades.

## Current workflow

1. Load the thematic ticker universe from `src/agents/ticker_universe.json`.
2. Download adjusted daily OHLCV market data.
3. Build momentum, moving-average, RSI, MACD, volatility, and liquidity features.
4. Label whether a stock reaches a 10% closing-price gain in the next 50 sessions.
5. Evaluate XGBoost on a chronological holdout separated by a 50-session embargo.
6. Retrain on the latest labelled window and rank the latest candidates.
7. Save the model, metrics, feature importance, and predictions for audit.

The embargo is important: it stops a training label's forward-looking window
from overlapping the validation period. Validation accuracy is also compared
with a majority-class baseline because accuracy alone can be misleading.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Run the research pipeline

From the repository root:

```bash
python3 src/data/download_market_data.py \
  --universe src/agents/ticker_universe.json \
  --output data/raw/market_data.parquet

python3 src/agents/train_xgboost.py --device cpu
```

Use `--device cuda` only when the installed XGBoost build and machine support it.
Generated files are written under `data/processed/` and `data/predictions/`.

## What the metrics mean

Treat the generated candidates as research output, not trading instructions.
Before paper trading, the model should demonstrate stable ROC AUC, precision,
and returns across multiple walk-forward periods and against SPY, QQQ, and a
simple momentum baseline. Risk checks and broker execution are intentionally
outside this first milestone.

## Safety boundary

The code currently has no broker connection and cannot submit orders. Paper
trading, deterministic risk rules, approval gates, idempotent order handling,
and reconciliation should be built and tested before any live integration.
