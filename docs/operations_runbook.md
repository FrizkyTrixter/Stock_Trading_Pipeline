# Operations Runbook

## Daily paper run

Validate configuration, confirm health and kill-switch state, run the fixture or configured provider workflow, review model approval and data freshness, inspect risk/reconciliation results, then import the ERP batch. Never infer completion from broker submission alone.

## Failure actions

- Failed run: retain run/correlation IDs and artifacts; fix the first failed invariant; resume only retry-safe stages.
- Stale data/account: defer all orders; refresh through the configured read-only provider; rerun quality/freshness checks.
- Provider outage: use a permitted replay/fixture for tests; do not manufacture current data.
- Malformed agent output or fabricated evidence: persist sanitized failure, alert, and abstain.
- Broker ambiguity: do not retry; reconcile client order ID/idempotency key with broker state.
- Reconciliation mismatch: activate kill switch, alert, investigate; do not silently repair ledger entries.
- Kill switch: preserve its reason; disable only after documented human investigation.
- ERP failure: retain batch in dead-letter, fix transport/import validation, replay the same batch ID; idempotency prevents duplicates.
- Model rollback: deprecate the current registry record and explicitly approve a prior integrity-checked artifact.
- Credential rotation: activate kill switch if broker/ERP credentials are affected, rotate out of band, verify redaction, then rerun readiness.

