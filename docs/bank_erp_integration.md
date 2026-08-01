# Bank ERP Integration

The trading system emits contract `1.0.0` batches containing canonical decimal-string investment events, stable source/event IDs, content hashes, and an optional HMAC. It supplies filesystem transport, export history, and dead-letter behavior. An authenticated HTTP transport is an intentional future adapter.

Bank ERP has an isolated `InvestmentBatchImporter` and CLI. It validates contract version/source, required fields, event types, currencies, timezone-aware timestamps, event hashes, batch hash, and optional HMAC. Import is transactional. Batch IDs and `(source_system, event_external_id)` are unique. Existing accounts and CSV transactions are untouched; external investment accounts use an explicit mapping table. Corrections are new events, never silent overwrites.

```powershell
$env:BANK_ERP_SQLITE_PATH="C:\path\bank_erp.db" # optional test override
python scripts/init_database.py
php scripts/import_investment_batch.php C:\path\erp_batch.json
```

`public/investments.php` is a read-only event report. Batches never contain broker/LLM/news credentials, raw prompts, authorization headers, or provider secrets.

