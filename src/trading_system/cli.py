"""Locally runnable commands used unchanged by GitHub Actions."""

import argparse
import json
from pathlib import Path
from typing import Any

from .config import load_settings
from .daily import DailyMarketCycle
from .erp_integration import (
    ERPExportService,
    FileSystemTransport,
    HttpERPTransport,
    build_batch,
    strategy_event,
)
from .market_data import YahooFinanceMarketDataService
from .research import OpenAIUniverseResearchProvider, UniverseResearchService
from .signals import XGBoostSignalService
from .storage import Storage


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-system",
        description="Yahoo Finance quantitative research and simulated-trading platform",
    )
    parser.add_argument("--config", type=Path, default=Path("config/base.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("config-validate")
    research = commands.add_parser("research-universe")
    research.add_argument("--period")
    research.add_argument("--force", action="store_true")
    update = commands.add_parser("update-market-data")
    update.add_argument("--start", default="2015-01-01")
    eod = commands.add_parser("run-eod")
    eod.add_argument("--model", type=Path, default=Path("data/processed/xgboost_model.joblib"))
    status = commands.add_parser("run-status")
    status.add_argument("run_id")
    return parser


def _market(settings: Any) -> YahooFinanceMarketDataService:
    return YahooFinanceMarketDataService(
        cache_dir=settings.market_data_cache,
        batch_size=settings.yahoo_batch_size,
        max_retries=settings.yahoo_max_retries,
        backoff_seconds=settings.yahoo_backoff_seconds,
        rate_limit_seconds=settings.yahoo_rate_limit_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    if args.command == "config-validate":
        safe = settings.model_dump(mode="json", exclude={"erp_hmac_secret"})
        _json({"valid": True, "execution_mode": "simulation-only", "settings": safe})
        return 0
    storage = Storage(settings.database_path)
    try:
        if args.command == "research-universe":
            provider = OpenAIUniverseResearchProvider(settings.llm_model)
            service = UniverseResearchService(
                storage,
                _market(settings),
                provider,
                settings.investment_theme,
                settings.universe_size,
                settings.ai_infrastructure,
            )
            run_id = service.run(period=args.period, force=args.force)
            run = storage.row("SELECT * FROM universe_runs WHERE id=?", (run_id,))
            if run is None:
                raise RuntimeError("Persisted universe could not be reloaded")
            members = storage.universe_members(run_id)
            sources = storage.rows(
                "SELECT * FROM research_sources WHERE universe_run_id=?", (run_id,)
            )
            events = [
                strategy_event(
                    "UNIVERSE_RESEARCH", run_id, f"Monthly AI universe {run['period']}", run
                )
            ]
            events.extend(
                strategy_event(
                    "UNIVERSE_MEMBER",
                    f"{run_id}:{item['ticker']}",
                    f"Universe member {item['ticker']}",
                    item,
                    symbol=item["ticker"],
                )
                for item in members
            )
            events.extend(
                strategy_event(
                    "RESEARCH_SOURCE",
                    item["id"],
                    f"Research source for {item['ticker']}",
                    item,
                    symbol=item["ticker"],
                )
                for item in sources
            )
            transport = (
                HttpERPTransport(settings.erp_endpoint)
                if settings.erp_endpoint
                else FileSystemTransport(settings.artifact_root / "erp-outbox")
            )
            export = ERPExportService(
                storage, transport, settings.artifact_root / "erp-dead-letter"
            )
            erp_location = export.export(
                build_batch(
                    settings.erp_account_external_id, tuple(events), settings.erp_hmac_secret
                )
            )
            _json(
                {
                    "status": "completed",
                    "universe_run_id": run_id,
                    "period": args.period or service.period_for(),
                    "size": settings.universe_size,
                    "erp_sync": erp_location,
                }
            )
            return 0
        if args.command == "update-market-data":
            universe = storage.active_universe()
            if universe is None:
                raise RuntimeError("No active universe; run research-universe first")
            tickers = tuple(item["ticker"] for item in storage.universe_members(universe["id"]))
            path = _market(settings).update_cache(tickers + settings.benchmarks, start=args.start)
            _json({"status": "completed", "path": str(path), "symbols": len(tickers)})
            return 0
        if args.command == "run-eod":
            transport = (
                HttpERPTransport(settings.erp_endpoint)
                if settings.erp_endpoint
                else FileSystemTransport(settings.artifact_root / "erp-outbox")
            )
            exporter = ERPExportService(
                storage, transport, settings.artifact_root / "erp-dead-letter"
            )
            result = DailyMarketCycle(
                settings=settings,
                storage=storage,
                market_data=_market(settings),
                signals=XGBoostSignalService(args.model),
                exporter=exporter,
            ).run()
            _json(result)
            return 0
        if args.command == "run-status":
            status_record = storage.row("SELECT * FROM strategy_runs WHERE id=?", (args.run_id,))
            if status_record is None:
                raise RuntimeError("run not found")
            _json(status_record)
            return 0
    finally:
        storage.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
