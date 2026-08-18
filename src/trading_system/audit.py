"""Structured JSON logging and durable domain audit events."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from .clock import utc_now
from .security import redact


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": utc_now().isoformat(),
            "level": record.levelname,
            "service": "trading-system",
            "component": getattr(record, "component", record.name),
            "event_name": getattr(record, "event_name", "log"),
            "outcome": getattr(record, "outcome", "info"),
            "message": record.getMessage(),
        }
        for key in ("run_id", "stage_id", "correlation_id", "causation_id", "ticker"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(redact(payload), sort_keys=True)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("trading_system")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


@dataclass(frozen=True)
class Alert:
    key: str
    severity: str
    message: str


class AlertSink:
    def emit(self, alert: Alert) -> None:
        raise NotImplementedError


class TestAlertSink(AlertSink):
    __test__ = False

    def __init__(self) -> None:
        self.alerts: list[Alert] = []
        self._keys: set[str] = set()

    def emit(self, alert: Alert) -> None:
        if alert.key not in self._keys:
            self.alerts.append(alert)
            self._keys.add(alert.key)
