# ADR 0002: Explicit orchestration

Status: accepted, 2026-08-01.

Use a visible in-process orchestrator with run IDs, locks, persisted stage status, timing, and fail-fast invariants. Hidden agent-to-agent conversation was rejected because it is difficult to resume, audit, or test. A distributed workflow engine is deferred until scale justifies it.

