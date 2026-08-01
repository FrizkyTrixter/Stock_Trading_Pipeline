# Risk Management

The risk engine is deterministic and produces a machine-readable `RiskCheck` for every rule. It checks executable action, positive quantity, order and position notional, position/equity percentage, portfolio gross exposure, sector exposure, open-position count, cash reserve, daily turnover, daily realized loss, drawdown, orders per day, market/account freshness, restricted symbols, and kill switch.

Sizing is deterministic fixed-notional with a slippage buffer, available-cash cap, broker fractionality capability, and round-down semantics. Fixed portfolio percentage and volatility-targeted policies remain configuration extensions; unrestricted Kelly sizing is not supported. Shorting, leverage, options, and fractional shares are disabled unless a future deterministic policy and broker capability explicitly enable them.

Outcomes are approved, approved-with-resize, rejected, deferred, or approval-required. The current conservative entry path returns approval-required after all checks pass. Every material intent change invalidates the approval hash. Paper auto-approval creates an exact immutable record; live mode forbids auto-approval.

