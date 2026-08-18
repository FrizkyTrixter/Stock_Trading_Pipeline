import numpy as np
import pandas as pd

from trading_system.backtesting import BacktestConfig, run_backtest
from trading_system.features import (
    EMBARGO_SESSIONS,
    HORIZON,
    TARGET_RETURN,
    build_features,
    chronological_split_dates,
    feature_columns,
    leakage_audit,
)
from trading_system.modeling import metrics


def price_panel(periods=400):
    dates = pd.bdate_range("2024-01-01", periods=periods)
    close = 100 * np.power(1.003, np.arange(periods))
    return pd.DataFrame(
        {
            "Date": dates,
            "Ticker": "TEST",
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000,
        }
    )


def test_features_preserve_target_embargo_and_no_leakage() -> None:
    frame = price_panel()
    panel = build_features(frame)
    assert HORIZON == 50 and TARGET_RETURN == 0.10 and EMBARGO_SESSIONS == 50
    assert panel.tail(HORIZON)["Target"].isna().all()
    columns = feature_columns(panel)
    assert columns and not leakage_audit(panel, columns)
    dates = list(pd.bdate_range("2024-01-01", periods=400))
    train, validation = chronological_split_dates(dates, 200, 50)
    assert dates.index(validation[0]) - dates.index(train[-1]) - 1 == 50


def test_backtest_next_session_costs_and_metrics() -> None:
    prices = price_panel(20)
    signals = pd.DataFrame({"Date": [prices.iloc[0]["Date"]], "Ticker": ["TEST"], "Score": [0.9]})
    report = run_backtest(
        signals,
        prices,
        BacktestConfig(max_positions=1, holding_sessions=2, commission_per_trade=1.0),
    )
    assert report.trade_count == 1 and report.total_return > 0
    measured = metrics(pd.Series([0, 1, 1, 0]), np.array([0.1, 0.8, 0.7, 0.2]))
    assert measured["accuracy"] == 1.0 and measured["roc_auc"] == 1.0
