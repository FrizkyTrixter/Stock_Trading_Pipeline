# ADR 0008: Vendor-neutral local observability

Status: accepted, 2026-08-01.

Use structured JSON logs, durable audit records, Prometheus-compatible counter text, health categories, and pluggable deduplicated alerts. A heavy distributed telemetry stack is unnecessary for local paper mode and can be added behind these boundaries later.
