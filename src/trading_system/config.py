"""Layered, typed configuration with fail-closed live-mode validation."""

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    maximum_order_notional: Decimal = Decimal("10000")
    maximum_position_notional: Decimal = Decimal("25000")
    maximum_position_percent: Decimal = Decimal("0.20")
    maximum_gross_exposure: Decimal = Decimal("0.80")
    maximum_sector_exposure: Decimal = Decimal("0.30")
    maximum_open_positions: int = 20
    minimum_cash_reserve: Decimal = Decimal("1000")
    maximum_daily_turnover: Decimal = Decimal("25000")
    maximum_daily_realized_loss: Decimal = Decimal("1000")
    maximum_drawdown: Decimal = Decimal("0.10")
    maximum_orders_per_day: int = 20
    maximum_price_deviation: Decimal = Decimal("0.02")
    restricted_symbols: tuple[str, ...] = ()


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    environment: str = "development"
    trading_mode: str = "paper"
    enable_live_trading: bool = False
    live_adapter_enabled: bool = False
    live_execution_tests_passed: bool = False
    live_warning_acknowledged: bool = False
    broker_credentials_present: bool = False
    database_path: Path = Path("data/trading_system.db")
    artifact_root: Path = Path("artifacts")
    market_data_max_age_seconds: int = 129600
    account_max_age_seconds: int = 300
    model_probability_threshold: Decimal = Field(default=Decimal("0.60"), ge=0, le=1)
    maximum_uncertainty: Decimal = Field(default=Decimal("0.40"), ge=0, le=1)
    paper_auto_approve: bool = True
    risk: RiskLimits = Field(default_factory=RiskLimits)

    @model_validator(mode="after")
    def validate_mode(self) -> "Settings":
        if self.trading_mode not in {"paper", "live"}:
            raise ValueError("trading_mode must be paper or live")
        if self.trading_mode == "live" and self.paper_auto_approve:
            raise ValueError("live mode forbids automatic approval")
        return self

    def live_static_gates(self) -> dict[str, bool]:
        return {
            "TRADING_MODE=live": self.trading_mode == "live",
            "ENABLE_LIVE_TRADING=true": self.enable_live_trading,
            "valid_broker_credentials": self.broker_credentials_present,
            "live_adapter_explicitly_enabled": self.live_adapter_enabled,
            "live_execution_tests_passed": self.live_execution_tests_passed,
            "warning_acknowledged": self.live_warning_acknowledged,
        }


ENV_MAP: dict[str, tuple[str, Any]] = {
    "TRADING_ENVIRONMENT": ("environment", str),
    "TRADING_MODE": ("trading_mode", str),
    "ENABLE_LIVE_TRADING": ("enable_live_trading", bool),
    "LIVE_ADAPTER_ENABLED": ("live_adapter_enabled", bool),
    "LIVE_EXECUTION_TESTS_PASSED": ("live_execution_tests_passed", bool),
    "LIVE_WARNING_ACKNOWLEDGED": ("live_warning_acknowledged", bool),
}


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"Invalid boolean value: {value}")
    return normalized in {"true", "1", "yes"}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration must be an object: {path}")
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(
    base_path: Path = Path("config/base.yaml"),
    environment_path: Path | None = Path("config/paper.yaml"),
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Load defaults, base, environment, environment variables, then CLI overrides."""
    data = _deep_merge({}, _read_yaml(base_path))
    if environment_path is not None:
        data = _deep_merge(data, _read_yaml(environment_path))
    for env_name, (field_name, cast) in ENV_MAP.items():
        if env_name in os.environ:
            raw = os.environ[env_name]
            data[field_name] = _parse_bool(raw) if cast is bool else cast(raw)
    data["broker_credentials_present"] = bool(os.getenv("BROKER_API_KEY"))
    if overrides:
        data = _deep_merge(data, overrides)
    return Settings.model_validate(data)
