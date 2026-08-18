# Bank ERP integration

Bank ERP dispatches Actions using a server-side fine-grained token with **Actions: write** and
**Metadata: read** on the Stock repository. The token never appears in HTML or JavaScript. Pipeline
results return through `ERP_ENDPOINT` as schema `1.0.0` batches with canonical event/batch SHA-256
hashes and `ERP_HMAC_SECRET`. The ERP verifies the complete batch before a transaction and rejects or
rolls back malformed input. Batch IDs and source event IDs make replay safe.
