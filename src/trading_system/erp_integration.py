"""Versioned, integrity-protected ERP export boundary."""

from pathlib import Path
from typing import Protocol

from .clock import utc_now
from .ids import new_id
from .security import sha256_json, sign_json
from .storage import Storage
from .types import ERPEvent, ERPExportBatch, Fill


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


def event_hash_payload(event: ERPEvent | dict[str, object]) -> dict[str, object]:
    data = event.model_dump(mode="json") if isinstance(event, ERPEvent) else dict(event)
    data.pop("content_hash", None)
    return data


def fill_to_event(fill: Fill, currency: str = "USD") -> ERPEvent:
    gross = fill.quantity * fill.unit_price
    net = -(gross + fill.fee) if fill.side == "buy" else gross - fill.fee
    draft = ERPEvent(
        event_external_id=fill.fill_id,
        event_type="fill",
        effective_at=fill.timestamp,
        currency=currency,
        symbol=fill.ticker,
        quantity=fill.quantity,
        unit_price=fill.unit_price,
        gross_amount=gross,
        fee_amount=fill.fee,
        net_amount=net,
        order_id=fill.broker_order_id,
        fill_id=fill.fill_id,
        description=f"Paper {fill.side} fill for {fill.ticker}",
        metadata={"mode": "paper"},
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
