# Security Policy

Do not report a vulnerability through trading logs or commit credentials. Remove secrets, preserve relevant safe evidence, activate the kill switch if execution integrity is in doubt, and rotate affected credentials before resuming.

Secrets are environment-only and are redacted by key name and bearer-token pattern. News text is untrusted; production analyzers must ignore embedded instructions and return evidence-linked strict schemas. Critical model and ERP artifacts use SHA-256 integrity hashes. ERP HMAC verification is enabled when both sides receive `ERP_HMAC_SECRET` out of band.

Live trading is disabled by default and no enabled live adapter is supplied. Do not weaken or combine the independent execution gates. Never add broker credentials to fixtures, CI, SQLite, logs, prompts, or Bank ERP batches.

See `docs/threat_model.md` for assets, threats, controls, and residual risks.

