# Security

This repository has no real-trading or brokerage integration. Do not add one to this simulation
runtime. LLM and article content are untrusted; validate before persistence and escape in the UI.
Secrets are environment-only. ERP batches use canonical SHA-256 event/batch hashes plus HMAC and are
sent over HTTPS. Report leaked keys privately, rotate them, inspect logs/artifacts, and replay only
the original idempotent batch after remediation.
