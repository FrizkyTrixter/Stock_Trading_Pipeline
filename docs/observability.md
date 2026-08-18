# Observability

JSON log records include UTC time, level, service, component, event, outcome, and available run/stage/correlation/causation/ticker context. Redaction covers secret-like keys and bearer tokens. Material domain records are stored separately from prose logs.

`Metrics` emits a Prometheus-compatible text form for counters. Intended metric families cover runs/stages/retries; market symbols/quality/nulls; model age/distribution/drift; agent validation/latency/abstention/evidence; recommendations/risk/orders/fills/exposure/P&L; and ERP success/duplicate/dead-letter counts.

Health reports process, dependency, data freshness, model, broker, ERP, kill switch, static gate failures, and live readiness. Live readiness is false by default. Alert sinks deduplicate by key; console/log production sinks can implement the same interface as the tested in-memory sink.

