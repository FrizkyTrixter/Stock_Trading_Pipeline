"""Versioned, integrity-protected ERP export boundary."""

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen

from .clock import utc_now
from .ids import new_id
from .security import sha256_json, sign_json
from .storage import Storage
from .types import ERPEvent, ERPExportBatch


class ERPTransport(Protocol):
    def send(self, batch: ERPExportBatch) -> str: ...


class FileSystemTransport:
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.destination.mkdir(parents=True, exist_ok=True)

    def send(self, batch: ERPExportBatch) -> str:
        final_path = self.destination / f"{batch.batch_id}.json"
        temporary = final_path.with_suffix(".json.tmp")
        temporary.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(final_path)
        return str(final_path)


class HttpERPTransport:
    """Server-to-server signed batch delivery; no database credentials are shared."""

    def __init__(self, endpoint: str, timeout_seconds: int = 30) -> None:
        if not endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("ERP endpoint must use HTTPS (HTTP is allowed only for localhost)")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def send(self, batch: ERPExportBatch) -> str:
        payload = batch.model_dump_json().encode("utf-8")
        request = Request(  # noqa: S310 - constructor receives a validated endpoint
            self.endpoint,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "stock-pipeline/1"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            body = response.read(1_000_000).decode("utf-8")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"ERP returned HTTP {response.status}: {body[:200]}")
        result = json.loads(body)
        return str(result.get("batch_id", batch.batch_id))


def event_hash_payload(event: ERPEvent | dict[str, object]) -> dict[str, object]:
    data = event.model_dump(mode="json") if isinstance(event, ERPEvent) else dict(event)
    data.pop("content_hash", None)
    return data


def strategy_event(
    event_type: str,
    external_id: str,
    description: str,
    metadata: Mapping[str, object],
    *,
    symbol: str | None = None,
    effective_at: datetime | None = None,
) -> ERPEvent:
    """Create an integrity-protected normalized strategy event."""
    safe_metadata = {key: value for key, value in metadata.items() if value is not None}
    draft = ERPEvent(
        event_external_id=external_id,
        event_type=event_type,
        effective_at=effective_at or utc_now(),
        currency="USD",
        symbol=symbol,
        description=description,
        metadata=safe_metadata,
        content_hash="0" * 64,
    )
    return draft.model_copy(update={"content_hash": sha256_json(event_hash_payload(draft))})


def build_batch(
    account_external_id: str,
    events: tuple[ERPEvent, ...],
    secret: str | None = None,
) -> ERPExportBatch:
    batch_id = new_id("erp_batch")
    integrity_payload = {
        "schema_version": "1.0.0",
        "batch_id": batch_id,
        "source_system": "stock-trading-pipeline",
        "account_external_id": account_external_id,
        "events": [event.model_dump(mode="json") for event in events],
    }
    content_hash = sha256_json(integrity_payload)
    signature = sign_json(integrity_payload, secret) if secret else None
    return ERPExportBatch(
        batch_id=batch_id,
        account_external_id=account_external_id,
        events=events,
        content_hash=content_hash,
        signature=signature,
        status="ready",
        data_as_of=max((event.effective_at for event in events), default=utc_now()),
    )


class ERPExportService:
    def __init__(self, storage: Storage, transport: ERPTransport, dead_letter: Path) -> None:
        self.storage = storage
        self.transport = transport
        self.dead_letter = dead_letter

    def export(self, batch: ERPExportBatch) -> str:
        self.storage.save("erp_export_batch", batch.batch_id, batch.run_id, "pending", batch)
        try:
            location = self.transport.send(batch)
        except Exception:
            self.dead_letter.mkdir(parents=True, exist_ok=True)
            path = self.dead_letter / f"{batch.batch_id}.json"
            path.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
            self.storage.save(
                "erp_export_batch", batch.batch_id, batch.run_id, "dead_letter", batch
            )
            raise
        self.storage.save("erp_export_batch", batch.batch_id, batch.run_id, "exported", batch)
        return location
