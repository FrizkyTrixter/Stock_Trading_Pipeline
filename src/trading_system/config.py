"""Central, fail-fast configuration for research and simulated trading only."""

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RiskLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    maximum_order_notional: Decimal = Decimal("10000")
    maximum_position_notional: Decimal = Decimal("25000")
    maximum_position_percent: Decimal = Decimal("0.20")
    maximum_gross_exposure: Decimal = Decimal("0.80")
    maximum_sector_exposure: Decimal = Decimal("0.35")
    maximum_open_positions: int = 20
    minimum_cash_reserve: Decimal = Decimal("1000")
    maximum_daily_turnover: Decimal = Decimal("25000")
    maximum_daily_realized_loss: Decimal = Decimal("1000")
    maximum_drawdown: Decimal = Decimal("0.20")
    maximum_orders_per_day: int = 40
    maximum_price_deviation: Decimal = Decimal("0.02")
    stop_loss_percent: Decimal = Field(default=Decimal("0.08"), gt=0, lt=1)
    take_profit_percent: Decimal | None = Field(default=Decimal("0.30"), gt=0)
    restricted_symbols: tuple[str, ...] = ()


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    environment: str = "development"
    database_path: Path = Path("data/trading_system.db")
    artifact_root: Path = Path("artifacts")
    market_data_cache: Path = Path("data/cache/yahoo")
    initial_capital: Decimal = Field(default=Decimal("100000"), gt=0)
    universe_size: int = Field(default=100, ge=100, le=100)
    universe_refresh: str = "monthly"
    investment_theme: str = "AI infrastructure and configurable growth sectors"
    llm_provider: str = "openai"
    llm_model: str = "gpt-5.5"
    model_version: str = "xgboost-current"
    model_probability_threshold: Decimal = Field(default=Decimal("0.60"), ge=0, le=1)
    allocation_policy: str = "capped_probability_weighted"
    benchmarks: tuple[str, ...] = ("SPY", "QQQ")
    yahoo_batch_size: int = Field(default=50, ge=1, le=200)
    yahoo_max_retries: int = Field(default=3, ge=1, le=10)
    yahoo_backoff_seconds: float = Field(default=1.0, ge=0)
    yahoo_rate_limit_seconds: float = Field(default=0.25, ge=0)
    market_data_max_age_seconds: int = 129600
    erp_endpoint: str | None = None
    erp_account_external_id: str = "simulated-portfolio"
    erp_hmac_secret: str | None = None
    risk: RiskLimits = Field(default_factory=RiskLimits)

    @field_validator("benchmarks", mode="before")
    @classmethod
    def parse_benchmarks(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip().upper() for item in value.split(",") if item.strip())
        return value

    @model_validator(mode="after")
    def simulation_only(self) -> "Settings":
        if self.universe_refresh != "monthly":
            raise ValueError("universe_refresh must be monthly")
        if not self.benchmarks:
            raise ValueError("at least one benchmark is required")
        if self.erp_endpoint and not self.erp_hmac_secret:
            raise ValueError("ERP_HMAC_SECRET is required when ERP_ENDPOINT is configured")
        return self


ENV_MAP: dict[str, tuple[str, Any]] = {
    "TRADING_ENVIRONMENT": ("environment", str),
    "TRADING_DATABASE_PATH": ("database_path", Path),
    "ARTIFACT_ROOT": ("artifact_root", Path),
    "MARKET_DATA_CACHE": ("market_data_cache", Path),
    "INITIAL_CAPITAL": ("initial_capital", Decimal),
    "UNIVERSE_SIZE": ("universe_size", int),
    "UNIVERSE_REFRESH": ("universe_refresh", str),
    "INVESTMENT_THEME": ("investment_theme", str),
    "LLM_PROVIDER": ("llm_provider", str),
    "LLM_MODEL": ("llm_model", str),
    "MODEL_VERSION": ("model_version", str),
    "MODEL_THRESHOLD": ("model_probability_threshold", Decimal),
    "BENCHMARKS": ("benchmarks", str),
    "ERP_ENDPOINT": ("erp_endpoint", str),
    "ERP_ACCOUNT_EXTERNAL_ID": ("erp_account_external_id", str),
    "ERP_HMAC_SECRET": ("erp_hmac_secret", str),
}


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
        result[key] = (
            _deep_merge(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else value
        )
    return result


def load_settings(
    base_path: Path = Path("config/base.yaml"),
    environment_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    data = _read_yaml(base_path)
    if environment_path is not None:
        data = _deep_merge(data, _read_yaml(environment_path))
    for env_name, (field_name, cast) in ENV_MAP.items():
        if env_name in os.environ:
            data[field_name] = cast(os.environ[env_name])
    if overrides:
        data = _deep_merge(data, overrides)
    return Settings.model_validate(data)
