"""Research-only next-session backtest, deliberately separate from broker execution."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    score_threshold: float = 0.60
    max_positions: int = 10
    holding_sessions: int = 20
    slippage_bps: float = 10.0
    commission_per_trade: float = 1.0
    maximum_volume_fraction: float = 0.01
    starting_cash: float = 100_000.0


@dataclass(frozen=True)
class BacktestReport:
    period: tuple[str, str]
    total_return: float
    benchmark_return: float | None
    maximum_drawdown: float
    turnover: float
    hit_rate: float
    average_exposure: float
    trade_count: int
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


def run_backtest(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    config: BacktestConfig | None = None,
    benchmark: pd.DataFrame | None = None,
) -> BacktestReport:
    """Buy ranked signals at next-session open and exit after a fixed holding period."""
    cfg = config or BacktestConfig()
    required_signals = {"Date", "Ticker", "Score"}
    required_prices = {"Date", "Ticker", "Open", "Close", "Volume"}
    if not required_signals.issubset(signals) or not required_prices.issubset(prices):
        raise ValueError("Backtest input columns are incomplete")
    ordered = prices.sort_values(["Ticker", "Date"]).copy()
    ordered["Entry"] = ordered.groupby("Ticker")["Open"].shift(-1)
    ordered["Exit"] = ordered.groupby("Ticker")["Close"].shift(-cfg.holding_sessions)
    ordered["EntryVolume"] = ordered.groupby("Ticker")["Volume"].shift(-1)
    candidates = signals[signals["Score"] >= cfg.score_threshold].copy()
    candidates = (
        candidates.sort_values(["Date", "Score"], ascending=[True, False])
        .groupby("Date")
        .head(cfg.max_positions)
    )
    trades = candidates.merge(
        ordered[["Date", "Ticker", "Entry", "Exit", "EntryVolume"]],
        on=["Date", "Ticker"],
        how="left",
    ).dropna(subset=["Entry", "Exit"])
    if trades.empty:
        raise ValueError("No executable next-session trades")
    allocation = cfg.starting_cash / cfg.max_positions
    slippage = cfg.slippage_bps / 10_000
    trades["EntryCost"] = trades["Entry"] * (1 + slippage)
    trades["ExitProceeds"] = trades["Exit"] * (1 - slippage)
    trades["Quantity"] = np.floor(
        np.minimum(
            allocation / trades["EntryCost"],
            trades["EntryVolume"] * cfg.maximum_volume_fraction,
        )
    )
    trades = trades[trades["Quantity"] > 0]
    trades["PnL"] = (
        trades["Quantity"] * (trades["ExitProceeds"] - trades["EntryCost"])
        - 2 * cfg.commission_per_trade
    )
    trades["Notional"] = trades["Quantity"] * trades["EntryCost"]
    daily_pnl = trades.groupby("Date")["PnL"].sum().sort_index()
    equity = cfg.starting_cash + daily_pnl.cumsum()
    drawdown = equity / equity.cummax() - 1
    benchmark_return = None
    if benchmark is not None and not benchmark.empty:
        benchmark_return = float(benchmark["Close"].iloc[-1] / benchmark["Close"].iloc[0] - 1)
    return BacktestReport(
        period=(str(trades["Date"].min()), str(trades["Date"].max())),
        total_return=float(trades["PnL"].sum() / cfg.starting_cash),
        benchmark_return=benchmark_return,
        maximum_drawdown=float(drawdown.min()),
        turnover=float(trades["Notional"].sum() / cfg.starting_cash),
        hit_rate=float((trades["PnL"] > 0).mean()),
        average_exposure=float(min(1.0, trades["Notional"].mean() / cfg.starting_cash)),
        trade_count=int(len(trades)),
        assumptions=(
            "signals are known after their dated session",
            "entry uses next-session open plus slippage",
            "exit uses a future close only after the configured holding period",
            "commissions and entry-volume participation are enforced",
        ),
        limitations=(
            "point-in-time universe membership depends on supplied signal data",
            "corporate actions depend on adjusted input policy",
            "classification accuracy is not treated as profitability",
        ),
    )
