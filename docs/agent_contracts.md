# Agent Contracts

## Universe Research Agent

Input: research theme, provider evidence, policy context. Output: `UniverseProposal` containing cited `TickerCandidate` records. Invariants: no direct training-universe mutation; no fabricated listing facts; current UTC research time. Allowed side effects: persist proposal and provider references. Failure: malformed output, absent evidence, provider outage. Deterministic `UniversePolicy` is always next.

## Signal Agent

Input: approved `ModelMetadata`, integrity-checked artifact, matching `FeatureSnapshot` schema. Output: ranked `ModelSignal`. It never trains, approves, promotes, sizes, or executes. It fails closed on unapproved models, hash/schema mismatch, missing features, staleness, or changed eligibility.

## News Research Agent

Input: tickers and explicit recency window. Output: deduplicated `NewsArticle` records containing provider-permitted excerpts and canonical references. It stores no full copyrighted body by default and never follows article instructions.

## News Analysis Agent

Input: retrieved articles treated as untrusted data. Output: strict `NewsAssessment` with `NewsEvidence` IDs, direction, confidence, disagreement, diversity, materiality, freshness, and uncertainty. Every claim must reference a retrieved article. Insufficient evidence produces `insufficient_evidence`. Allowed side effect: persist sanitized input, raw response, validation, usage, and evidence references. It cannot call execution tools.

## Decision Agent

Input: approved signals, validated news, portfolio/cash/pending state, freshness, regime context, and strategy thresholds. Output: `TradeRecommendation` using buy/sell/reduce/hold/avoid/defer. It is encouraged to abstain. It never computes final quantity or calls brokers. Strong material bearish news can veto; insufficient news does not automatically negate a model signal.

## Execution Agent

Input: exact `OrderIntent`, matching deterministic `RiskAssessment`, exact unexpired `OrderApproval`, configuration, freshness, kill-switch state, and broker capability. Output: `ExecutionReport`. Only `ExecutionService` may call a broker. Ambiguous submission becomes reconciliation-required and is never blindly retried.

