# Operations runbook

1. Validate configuration with `trading-system config-validate`.
2. Run `research-universe` once per month; normal repeats reuse the existing period.
3. Review the signed ERP result and the 100-member count.
4. Allow `daily-market-cycle.yml` to run at 23:15 UTC on weekdays.
5. Review the JSON report, Actions status, ERP ingestion audit, decisions, stops, and snapshot.

Yahoo empty batches fail visibly after configured retries. A non-session or replay logs “No completed
US trading session since previous run” and performs no writes. ERP delivery failures retain the exact
signed batch in the dead-letter directory for an idempotent replay. Do not generate a new batch to
retry an existing one.

For a manual month refresh, use Bank ERP’s force control and its extra confirmation or dispatch
`monthly-research.yml` with `force=true`. For EOD, use the ERP control or
`manual-strategy-run.yml`. Secrets belong in GitHub Actions/ERP server configuration only.
