# Migration Guide

The old scripts remain valid. Install the package from the repository root and adopt `trading-system config validate` and the fixture daily run first. Historical generated data and models are not deleted or rewritten.

No target migration occurred: the target remains a 10% maximum close gain within 50 sessions; horizon and embargo remain 50 sessions; universe and default thresholds remain available. The legacy files were formatted and tested, not replaced. New components use versioned records and SHA-256 manifests; legacy artifacts lack those metadata and are not automatically approved.

Machine-specific shell scripts are retained as deprecated operational examples because their hard-coded paths are not portable. Replace them with the installable CLI and external scheduler. The GitHub market-data workflow no longer commits ignored/generated parquet; it uploads a seven-day artifact.

Bank ERP keeps existing account/transaction tables and pages. Database initialization adds isolated investment mapping, batch, event, and audit tables. Account mutations now require CSRF tokens. Set `BANK_ERP_SQLITE_PATH` only for isolated/test databases.

