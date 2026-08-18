import json
from datetime import UTC, datetime

import pytest

from trading_system.erp_integration import FileSystemTransport, build_batch, strategy_event
from trading_system.security import sign_json


def test_signed_versioned_batch_and_filesystem_transport(tmp_path) -> None:
    event = strategy_event(
        "TRADE_DECISION",
        "decision-1",
        "escaped <script>",
        {"ticker": "AAA", "reason": "untrusted"},
        symbol="AAA",
        effective_at=datetime(2026, 8, 17, tzinfo=UTC),
    )
    batch = build_batch("portfolio", (event,), "secret")
    assert batch.signature
    location = FileSystemTransport(tmp_path).send(batch)
    payload = json.loads(open(location, encoding="utf-8").read())
    unsigned = {
        key: payload[key]
        for key in ["schema_version", "batch_id", "source_system", "account_external_id", "events"]
    }
    assert payload["signature"] == sign_json(unsigned, "secret")
    assert payload["events"][0]["description"] == "escaped <script>"


def test_https_required_for_remote_erp() -> None:
    from trading_system.erp_integration import HttpERPTransport

    with pytest.raises(ValueError, match="HTTPS"):
        HttpERPTransport("http://example.com/ingest")
