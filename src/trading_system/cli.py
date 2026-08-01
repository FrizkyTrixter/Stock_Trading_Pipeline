"""Command-line entry point for safe local workflows."""

import argparse
import json
from pathlib import Path
from typing import Any

from .config import load_settings
from .observability import health
from .orchestration import run_fixture_demo
from .storage import Storage


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-system", description="Auditable paper-trading system"
    )
    parser.add_argument("--base-config", type=Path, default=Path("config/base.yaml"))
    parser.add_argument("--environment-config", type=Path, default=Path("config/paper.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config")
    config_sub = config.add_subparsers(dest="action", required=True)
    config_sub.add_parser("validate")

    run = commands.add_parser("run")
    run_sub = run.add_subparsers(dest="action", required=True)
    daily = run_sub.add_parser("daily")
    daily.add_argument(
        "--fixture",
        action="store_true",
        required=True,
        help="Use deterministic data and fake boundaries",
    )
    daily.add_argument("--workspace", type=Path, default=Path("artifacts/runs/fixture-daily"))
    status = run_sub.add_parser("status")
    status.add_argument("run_id")

    commands.add_parser("health")
    kill = commands.add_parser("kill-switch")
    kill_sub = kill.add_subparsers(dest="action", required=True)
    enable = kill_sub.add_parser("enable")
    enable.add_argument("--reason", required=True)
    kill_sub.add_parser("disable")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.base_config, args.environment_config)
    if args.command == "config":
        _json(
            {"valid": True, "settings": settings.model_dump(mode="json"), "live_readiness": False}
        )
        return 0
    if args.command == "run" and args.action == "daily":
        run = run_fixture_demo(args.workspace, settings)
        _json(run.model_dump(mode="json"))
        return 0
    storage = Storage(settings.database_path)
    try:
        if args.command == "health":
            _json(health(settings, storage))
            return 0
        if args.command == "kill-switch":
            if args.action == "enable":
                storage.set_kill_switch(True, args.reason)
            else:
                storage.set_kill_switch(False, "disabled by explicit operator command")
            _json({"kill_switch_active": storage.kill_switch_active()})
            return 0
        if args.command == "run" and args.action == "status":
            payload = storage.load("pipeline_run", args.run_id)
            if payload is None:
                parser.error("run not found")
            _json(payload)
            return 0
    finally:
        storage.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
