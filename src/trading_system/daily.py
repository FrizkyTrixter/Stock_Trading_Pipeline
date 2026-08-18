"""Once-per-completed-market-session strategy orchestration."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Protocol

import pandas as pd

from .allocation import CapitalAllocationPolicy
from .config import Settings
from .erp_integration import ERPExportService, build_batch, strategy_event
from .ids import new_id
from .market_data import MarketDataProvider
from .simulation import SimulatedExecutionEngine, StopLossPolicy
from .storage import Storage


class SignalProvider(Protocol):
    model_version: str

    def probabilities(
        self, frame: pd.DataFrame, tickers: tuple[str, ...]
    ) -> dict[str, Decimal]: ...


class DailyMarketCycle:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: Storage,
        market_data: MarketDataProvider,
        signals: SignalProvider,
        exporter: ERPExportService | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.market_data = market_data
        self.signals = signals
        self.exporter = exporter
        self.simulator = SimulatedExecutionEngine(storage, settings.initial_capital)

    def run(self) -> dict[str, object]:
        session = self.market_data.completed_session(self.settings.benchmarks[0])  # type: ignore[attr-defined]
        if session is None or self.storage.last_completed_session() == session.isoformat():
            return {
                "status": "skipped",
                "message": (
                    "No completed US trading session since previous run. Nothing to process."
                ),
            }
        universe = self.storage.active_universe()
        if universe is None:
            raise RuntimeError("No completed monthly universe is available")
        members = self.storage.universe_members(str(universe["id"]))
        if len(members) != self.settings.universe_size:
            raise RuntimeError(
                f"Active universe must contain exactly {self.settings.universe_size} members"
            )
        run_id = new_id("strategy_run")
        now = datetime.now(UTC).isoformat()
        try:
            self.storage.execute(
                "INSERT INTO strategy_runs VALUES (?, 'eod', ?, ?, 'running', ?, NULL, '{}', NULL)",
                (run_id, session.isoformat(), universe["id"], now),
            )
        except Exception as exc:
            existing = self.storage.row(
                "SELECT * FROM strategy_runs WHERE run_type='eod' AND market_session=?",
                (session.isoformat(),),
            )
            if existing:
                return {
                    "status": existing["status"],
                    "run_id": existing["id"],
                    "market_session": session.isoformat(),
                    "message": "Idempotent replay; the market session already has a run.",
                }
            raise exc
        try:
            tickers = tuple(str(item["ticker"]) for item in members)
            preexisting_positions = self.simulator.positions()
            all_symbols = tuple(
                dict.fromkeys(tickers + tuple(preexisting_positions) + self.settings.benchmarks)
            )
            history = self.market_data.history(
                all_symbols, start=session - timedelta(days=800), end=session + timedelta(days=1)
            )
            latest = self.market_data.latest(all_symbols)
            unavailable = [ticker for ticker in all_symbols if not latest[ticker].available]
            if unavailable:
                raise RuntimeError("Latest Yahoo data unavailable for: " + ", ".join(unavailable))
            prices = {ticker: latest[ticker].price for ticker in all_symbols}
            safe_prices = {ticker: price for ticker, price in prices.items() if price is not None}
            probabilities = self.signals.probabilities(history, tickers)
            ranked = sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
            for rank, (ticker, probability) in enumerate(ranked, 1):
                self.storage.execute(
                    "INSERT INTO model_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_id("signal"),
                        run_id,
                        universe["id"],
                        ticker,
                        self.signals.model_version,
                        str(probability),
                        rank,
                        session.isoformat(),
                        str(safe_prices[ticker]),
                        now,
                    ),
                )
            cash, _, _ = self.simulator.state()
            positions = self.simulator.positions()
            portfolio_value = cash + sum(
                qty * safe_prices[ticker] for ticker, (qty, _) in positions.items()
            )
            current_notionals = {
                ticker: qty * safe_prices[ticker] for ticker, (qty, _) in positions.items()
            }
            policy = CapitalAllocationPolicy(
                threshold=self.settings.model_probability_threshold,
                max_positions=self.settings.risk.maximum_open_positions,
                max_position_weight=self.settings.risk.maximum_position_percent,
                max_position_notional=self.settings.risk.maximum_position_notional,
                cash_reserve=self.settings.risk.minimum_cash_reserve,
            )
            allocations = policy.allocate(probabilities, portfolio_value, current_notionals)
            for item in allocations:
                current = current_notionals.get(item.ticker, Decimal("0"))
                current_weight = current / portfolio_value if portfolio_value else Decimal("0")
                self.storage.execute(
                    "INSERT INTO capital_allocations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_id("allocation"),
                        run_id,
                        item.ticker,
                        str(item.target_notional),
                        str(item.target_weight),
                        str(current),
                        str(current_weight),
                        item.action,
                        now,
                    ),
                )
            executions = []
            stop_policy = StopLossPolicy(self.settings.risk.stop_loss_percent)
            exited: set[str] = set()
            for ticker, (quantity, average_cost) in list(positions.items()):
                price = safe_prices.get(ticker)
                if price is None:
                    continue
                if stop_policy.breached(average_cost, price):
                    executions.append(
                        self.simulator.execute(
                            strategy_run_id=run_id,
                            universe_run_id=str(universe["id"]),
                            market_session=session,
                            ticker=ticker,
                            side="SELL",
                            quantity=quantity,
                            price=price,
                            decision_type="STOP_LOSS_EXIT",
                            reason="Closing price breached configured stop-loss threshold.",
                            metadata={
                                "entry_price": str(average_cost),
                                "stop_price": str(stop_policy.stop_price(average_cost)),
                            },
                        )
                    )
                    exited.add(ticker)
                elif ticker not in tickers:
                    executions.append(
                        self.simulator.execute(
                            strategy_run_id=run_id,
                            universe_run_id=str(universe["id"]),
                            market_session=session,
                            ticker=ticker,
                            side="SELL",
                            quantity=quantity,
                            price=price,
                            decision_type="UNIVERSE_REMOVAL",
                            reason="Security is no longer in the active monthly universe.",
                        )
                    )
                    exited.add(ticker)
                elif (
                    self.settings.risk.take_profit_percent is not None
                    and price
                    >= average_cost * (Decimal("1") + self.settings.risk.take_profit_percent)
                ):
                    executions.append(
                        self.simulator.execute(
                            strategy_run_id=run_id,
                            universe_run_id=str(universe["id"]),
                            market_session=session,
                            ticker=ticker,
                            side="SELL",
                            quantity=quantity,
                            price=price,
                            decision_type="TAKE_PROFIT_EXIT",
                            reason="Closing price reached the configured take-profit threshold.",
                        )
                    )
                    exited.add(ticker)
                elif (
                    probabilities.get(ticker, Decimal("0"))
                    < self.settings.model_probability_threshold
                ):
                    executions.append(
                        self.simulator.execute(
                            strategy_run_id=run_id,
                            universe_run_id=str(universe["id"]),
                            market_session=session,
                            ticker=ticker,
                            side="SELL",
                            quantity=quantity,
                            price=price,
                            decision_type="SIGNAL_EXIT",
                            reason="XGBoost probability fell below the configured model threshold.",
                        )
                    )
                    exited.add(ticker)
            positions = self.simulator.positions()
            cash, _, _ = self.simulator.state()
            for item in allocations:
                price = safe_prices[item.ticker]
                current_qty = positions.get(item.ticker, (Decimal("0"), Decimal("0")))[0]
                target_qty = (item.target_notional / price).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                )
                buy_qty = min(
                    target_qty - current_qty,
                    (cash / price).quantize(Decimal("1"), rounding=ROUND_DOWN),
                )
                if buy_qty > 0:
                    trade = self.simulator.execute(
                        strategy_run_id=run_id,
                        universe_run_id=str(universe["id"]),
                        market_session=session,
                        ticker=item.ticker,
                        side="BUY",
                        quantity=buy_qty,
                        price=price,
                        decision_type="MODEL_ENTRY",
                        reason=(
                            "Qualified through the XGBoost signal and deterministic "
                            "allocation policy."
                        ),
                        metadata={
                            "probability": str(item.probability),
                            "target_notional": str(item.target_notional),
                        },
                    )
                    executions.append(trade)
                    cash -= trade.notional + trade.fees
            holding_prices = {ticker: safe_prices[ticker] for ticker in self.simulator.positions()}
            snapshot = self.simulator.snapshot(
                strategy_run_id=run_id, market_session=session, prices=holding_prices
            )
            self._benchmarks(run_id, session, history, safe_prices)
            summary = {
                "status": "completed",
                "run_id": run_id,
                "market_session": session.isoformat(),
                "universe_run_id": universe["id"],
                "universe_period": universe["period"],
                "universe_size": len(members),
                "model_version": self.signals.model_version,
                "portfolio": snapshot,
                "model_picks": [
                    {"ticker": ticker, "probability": str(score)} for ticker, score in ranked[:10]
                ],
                "executions": [trade.__dict__ for trade in executions],
                "erp_sync": "not_configured",
            }
            if self.exporter:
                events = [
                    strategy_event(
                        "STRATEGY_RUN",
                        run_id,
                        f"EOD strategy run {session}",
                        summary,
                        effective_at=datetime.combine(session, datetime.min.time(), tzinfo=UTC),
                    ),
                    strategy_event(
                        "PORTFOLIO_SNAPSHOT",
                        str(snapshot["id"]),
                        f"Portfolio snapshot {session}",
                        snapshot,
                        effective_at=datetime.combine(session, datetime.min.time(), tzinfo=UTC),
                    ),
                ]
                for row in self.storage.rows(
                    "SELECT * FROM model_signals WHERE strategy_run_id=?", (run_id,)
                ):
                    events.append(
                        strategy_event(
                            "MODEL_SIGNAL",
                            row["id"],
                            f"XGBoost signal {row['ticker']}",
                            row,
                            symbol=row["ticker"],
                        )
                    )
                for row in self.storage.rows(
                    "SELECT * FROM capital_allocations WHERE strategy_run_id=?", (run_id,)
                ):
                    events.append(
                        strategy_event(
                            "CAPITAL_ALLOCATION",
                            row["id"],
                            f"Capital allocation {row['ticker']}",
                            row,
                            symbol=row["ticker"],
                        )
                    )
                for row in self.storage.rows(
                    "SELECT * FROM trade_decisions WHERE strategy_run_id=?", (run_id,)
                ):
                    events.append(
                        strategy_event(
                            "TRADE_DECISION", row["id"], row["reason"], row, symbol=row["ticker"]
                        )
                    )
                for row in self.storage.rows(
                    "SELECT * FROM simulated_trades WHERE strategy_run_id=?", (run_id,)
                ):
                    event_type = (
                        "STOP_LOSS_EXIT"
                        if "stop-loss" in row["reason"].lower()
                        else ("TRADE_BUY" if row["side"] == "BUY" else "TRADE_SELL")
                    )
                    events.append(
                        strategy_event(
                            event_type, row["id"], row["reason"], row, symbol=row["ticker"]
                        )
                    )
                for row in self.storage.rows(
                    "SELECT * FROM benchmark_snapshots WHERE strategy_run_id=?", (run_id,)
                ):
                    events.append(
                        strategy_event(
                            "BENCHMARK_SNAPSHOT",
                            row["id"],
                            f"Benchmark snapshot {row['ticker']}",
                            row,
                            symbol=row["ticker"],
                        )
                    )
                batch = build_batch(
                    self.settings.erp_account_external_id,
                    tuple(events),
                    self.settings.erp_hmac_secret,
                )
                summary["erp_sync"] = self.exporter.export(batch)
            report_path = self._write_report(summary)
            summary["report_path"] = str(report_path)
            self.storage.execute(
                "UPDATE strategy_runs SET status='completed', completed_at=?, "
                "summary_json=? WHERE id=?",
                (datetime.now(UTC).isoformat(), json.dumps(summary, default=str), run_id),
            )
            return summary
        except Exception as exc:
            self.storage.execute(
                "UPDATE strategy_runs SET status='failed', completed_at=?, "
                "error_message=? WHERE id=?",
                (datetime.now(UTC).isoformat(), str(exc), run_id),
            )
            raise

    def _benchmarks(
        self, run_id: str, session: date, frame: pd.DataFrame, prices: dict[str, Decimal]
    ) -> None:
        now = datetime.now(UTC).isoformat()
        for ticker in self.settings.benchmarks:
            rows = frame[frame["Ticker"] == ticker].sort_values("Date")
            if rows.empty:
                continue
            first = Decimal(str(rows.iloc[0]["Close"]))
            cumulative = (prices[ticker] - first) / first if first else Decimal("0")
            self.storage.execute(
                "INSERT OR IGNORE INTO benchmark_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("benchmark"),
                    run_id,
                    session.isoformat(),
                    ticker,
                    str(prices[ticker]),
                    str(cumulative),
                    now,
                ),
            )

    def _write_report(self, summary: dict[str, object]) -> Path:
        root = self.settings.artifact_root / "runs" / str(summary["market_session"])
        root.mkdir(parents=True, exist_ok=True)
        path = root / "daily-report.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)
        return path
