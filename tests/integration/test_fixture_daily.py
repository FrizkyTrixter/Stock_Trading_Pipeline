import json
import os
import sqlite3
import subprocess
from pathlib import Path

from trading_system.config import Settings
from trading_system.orchestration import run_fixture_demo

ERP_ROOT = (
    Path(__file__).resolve().parents[4] / "Bank_ERP_Aggregator-main" / "Bank_ERP_Aggregator-main"
)


def test_complete_fixture_run_and_idempotent_erp_import(tmp_path) -> None:
    run = run_fixture_demo(tmp_path / "run", Settings())
    assert run.status == "completed"
    assert run.summary["no_real_trades"] is True
    assert run.summary["order_state"] == "filled"
    assert run.summary["reconciliation_status"] == "matched"
    batch = Path(run.summary["erp_export_path"])
    database = tmp_path / "erp.db"
    environment = {
        **os.environ,
        "BANK_ERP_SQLITE_PATH": str(database),
        "ERP_HMAC_SECRET": "fixture-test-secret",
    }
    subprocess.run(
        ["python", "scripts/init_database.py"],
        cwd=ERP_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    first = subprocess.run(
        ["php", "scripts/import_investment_batch.php", str(batch.resolve())],
        cwd=ERP_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        ["php", "scripts/import_investment_batch.php", str(batch.resolve())],
        cwd=ERP_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(first.stdout)["imported"] == 1
    assert json.loads(second.stdout)["skipped"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM investment_events").fetchone()[0] == 1
