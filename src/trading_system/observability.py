"""Vendor-neutral local metrics and health categories."""

from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .storage import Storage


@dataclass
class Metrics:
    counters: dict[str, float] = field(default_factory=dict)

    def increment(self, name: str, amount: float = 1.0) -> None:
        self.counters[name] = self.counters.get(name, 0.0) + amount

    def prometheus(self) -> str:
        return (
            "\n".join(
                f"trading_system_{name} {value}" for name, value in sorted(self.counters.items())
            )
            + "\n"
        )


def health(
    settings: Settings, storage: Storage, model_ready: bool = False, erp_ready: bool = True
) -> dict[str, Any]:
    static_gates = settings.live_static_gates()
    return {
        "process_health": True,
        "dependency_health": True,
        "data_freshness": "unknown",
        "model_readiness": model_ready,
        "broker_readiness": settings.trading_mode == "paper",
        "erp_readiness": erp_ready,
        "kill_switch_active": storage.kill_switch_active(),
        "live_trading_readiness": False,
        "live_gate_failures": [name for name, passed in static_gates.items() if not passed],
    }
