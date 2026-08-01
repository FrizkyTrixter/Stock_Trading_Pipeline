"""Visible orchestration with persisted stages and a deterministic fixture daily run."""

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .approvals import approve
from .brokers import FakeBrokerAdapter
from .clock import utc_now
from .config import Settings
from .decisioning import DecisionPolicy
from .erp_integration import ERPExportService, FileSystemTransport, build_batch, fill_to_event
from .execution import ExecutionService
from .features import build_features, feature_columns, leakage_audit
from .ids import new_id
from .modeling import ModelRegistry, generate_signals, train_xgboost
from .news import DeterministicNewsAnalyzer, FixtureNewsProvider, validate_evidence
from .portfolio import PortfolioLedger
from .reconciliation import reconcile
from .risk import RiskEngine, size_fixed_notional
from .security import sha256_json
from .storage import Storage
from .types import FeatureSnapshot, NewsArticle, PipelineRun, PortfolioSnapshot

STAGES = (
    "validate_market_data",
    "build_features",
    "train_or_load_model",
    "evaluate_model",
    "generate_model_signals",
    "collect_news",
    "analyze_news",
    "snapshot_portfolio",
    "generate_trade_recommendations",
    "run_risk_checks",
    "request_approval",
    "execute_approved_orders",
    "reconcile_orders",
    "export_to_bank_erp",
    "generate_run_report",
)


class Orchestrator:
    def __init__(self, storage: Storage, workflow: str = "daily") -> None:
        self.storage = storage
        self.run_id = new_id("run")
        self.correlation_id = new_id("corr")
        self.workflow = workflow
        self.completed: list[str] = []

    def stage(self, name: str, operation: Callable[[], Any]) -> Any:
        started = perf_counter()
        self.storage.save("stage", f"{self.run_id}:{name}", self.run_id, "running", {"name": name})
        try:
            result = operation()
        except Exception as exc:
            self.storage.save(
                "stage",
                f"{self.run_id}:{name}",
                self.run_id,
                "failed",
                {"name": name, "error_type": type(exc).__name__},
            )
            raise
        self.completed.append(name)
        self.storage.save(
            "stage",
            f"{self.run_id}:{name}",
            self.run_id,
            "completed",
            {"name": name, "duration_ms": int((perf_counter() - started) * 1000)},
        )
        return result

    def acquire(self) -> None:
        self.storage.acquire_lock(self.workflow, self.run_id)

    def finish(self, summary: dict[str, Any]) -> PipelineRun:
        self.storage.release_lock(self.workflow, self.run_id)
        run = PipelineRun(
            id=self.run_id,
            run_id=self.run_id,
            correlation_id=self.correlation_id,
            workflow=self.workflow,
            stages=tuple(self.completed),
            summary=summary,
            status="completed",
        )
        self.storage.save("pipeline_run", self.run_id, self.run_id, "completed", run)
        return run


def fixture_market_data() -> pd.DataFrame:
    dates = pd.bdate_range(end=utc_now().date(), periods=620)
    rows: list[dict[str, Any]] = []
    for index, ticker in enumerate(("ALFA", "BETA", "GAMM", "DELT")):
        step = np.arange(len(dates), dtype=float)
        close = 50 + index * 10 + 0.025 * step + (4 + index) * np.sin(step / (8 + index))
        for position, date in enumerate(dates):
            price = max(close[position], 5.0)
            rows.append(
                {
                    "Date": date,
                    "Ticker": ticker,
                    "Open": price * 0.998,
                    "High": price * 1.01,
                    "Low": price * 0.99,
                    "Close": price,
                    "Volume": 1_000_000 + index * 100_000 + position * 10,
                }
            )
    return pd.DataFrame(rows)


def run_fixture_demo(root: Path, settings: Settings) -> PipelineRun:
    root.mkdir(parents=True, exist_ok=True)
    storage = Storage(root / "fixture.db")
    orchestrator = Orchestrator(storage, "fixture-daily")
    orchestrator.acquire()
    try:
        raw = fixture_market_data()
        orchestrator.stage(
            "validate_market_data",
            lambda: (
                None
                if (raw[["Open", "High", "Low", "Close"]] > 0).all().all()
                else (_ for _ in ()).throw(ValueError("invalid prices"))
            ),
        )
        panel = orchestrator.stage("build_features", lambda: build_features(raw))
        features = [
            name
            for name in feature_columns(panel)
            if name
            in {
                "Return_5d",
                "Return_20d",
                "Close_to_SMA_20",
                "RSI_14",
                "Volatility_20d",
                "Dollar_Volume",
            }
        ]
        findings = leakage_audit(panel, features)
        if findings:
            raise RuntimeError(f"Leakage audit failed: {findings}")
        registry = ModelRegistry(root / "models")
        trained = orchestrator.stage(
            "train_or_load_model",
            lambda: train_xgboost(
                panel, features, registry, train_days=200, validation_days=50, n_estimators=30
            ),
        )
        orchestrator.stage("evaluate_model", lambda: trained.evaluation)
        approved = registry.approve(trained.metadata.model_id, "fixture-promotion-policy")
        model, approved = registry.load_approved_model(approved.model_id)
        latest = panel[panel["Date"] == panel["Date"].max()].sort_values("Ticker")
        snapshots = tuple(
            FeatureSnapshot(
                ticker=str(row["Ticker"]),
                features={name: float(row[name]) for name in features},
                feature_manifest_hash=sha256_json(features),
                data_as_of=pd.Timestamp(row["Date"]).tz_localize("UTC").to_pydatetime(),
                status="valid",
            )
            for _, row in latest.iterrows()
        )
        signals = orchestrator.stage(
            "generate_model_signals",
            lambda: generate_signals(model, approved, snapshots, tuple(features)),
        )
        best = min(signals, key=lambda item: item.rank)
        article = NewsArticle(
            article_id="fixture-article-1",
            canonical_url="https://example.invalid/fixture-1",
            provider="fixture",
            headline=f"{best.ticker} expands after new contract",
            publication="Fixture Wire",
            publication_timestamp=utc_now() - timedelta(hours=1),
            retrieval_timestamp=utc_now(),
            tickers=(best.ticker,),
            excerpt="Reported growth and a signed contract.",
            content_hash=sha256_json("fixture article"),
            deduplication_key="fixture-1",
            status="collected",
        )
        articles = orchestrator.stage(
            "collect_news", lambda: FixtureNewsProvider((article,)).collect((best.ticker,))
        )
        assessment = orchestrator.stage(
            "analyze_news", lambda: DeterministicNewsAnalyzer().analyze(best.ticker, articles)
        )
        validate_evidence(assessment, articles)
        portfolio = orchestrator.stage(
            "snapshot_portfolio",
            lambda: PortfolioSnapshot(cash=Decimal("100000"), status="current"),
        )
        recommendation = orchestrator.stage(
            "generate_trade_recommendations",
            lambda: DecisionPolicy(probability_threshold=Decimal("0")).recommend(
                best, assessment, portfolio
            ),
        )
        quantity = size_fixed_notional(recommendation, Decimal("100"), portfolio.cash)
        assessment_risk, intent = orchestrator.stage(
            "run_risk_checks",
            lambda: RiskEngine(settings.risk, storage).evaluate(
                recommendation,
                portfolio,
                quantity,
                Decimal("100"),
                approved.model_id,
                sector="technology",
            ),
        )
        if intent is None:
            raise RuntimeError(f"Fixture risk rejection: {assessment_risk.rejection_reasons}")
        approval = orchestrator.stage("request_approval", lambda: approve(intent, "paper-auto"))
        broker = FakeBrokerAdapter(fill_price=Decimal("100"))
        execution = orchestrator.stage(
            "execute_approved_orders",
            lambda: ExecutionService(settings, storage, broker).execute(
                intent, approval, assessment_risk
            ),
        )
        reconciliation = orchestrator.stage(
            "reconcile_orders", lambda: reconcile((execution.broker_order,), broker.orders())
        )
        ledger = PortfolioLedger(Decimal("100000"))
        for fill in execution.fills:
            ledger.apply_fill(fill)
        snapshot = ledger.snapshot({best.ticker: Decimal("100")}, {best.ticker: "technology"})
        events = tuple(fill_to_event(fill) for fill in execution.fills)
        batch = build_batch(
            "fixture-investment-account",
            events,
            secret="fixture-test-secret",  # noqa: S106 - public deterministic fixture only
        )
        exporter = ERPExportService(
            storage, FileSystemTransport(root / "erp_outbox"), root / "erp_dead_letter"
        )
        export_path = orchestrator.stage("export_to_bank_erp", lambda: exporter.export(batch))
        summary = {
            "model_id": approved.model_id,
            "signal_ticker": best.ticker,
            "risk_outcome": assessment_risk.outcome.value,
            "order_state": execution.broker_order.state.value,
            "fill_count": len(execution.fills),
            "reconciliation_status": reconciliation.status,
            "portfolio_cash": str(snapshot.cash),
            "erp_batch_id": batch.batch_id,
            "erp_export_path": export_path,
            "no_real_trades": True,
        }
        orchestrator.stage("generate_run_report", lambda: summary)
        return orchestrator.finish(summary)
    except Exception:
        storage.release_lock(orchestrator.workflow, orchestrator.run_id)
        raise
    finally:
        storage.close()
