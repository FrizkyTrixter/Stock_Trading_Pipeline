# ADR 0007: Versioned ERP event contract

Status: accepted, 2026-08-01.

The trading package emits canonical versioned investment events through a transport boundary; it never writes ERP tables. Bank ERP imports transactionally with batch/event uniqueness, hashes, optional HMAC, mappings, and audit. Tight Python-to-PHP or shared-database coupling was rejected.

