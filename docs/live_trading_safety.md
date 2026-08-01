# Live Trading Safety

Live trading is unavailable by design. `DisabledLiveBrokerAdapter` always rejects and declares no live capability. Health always reports live readiness false.

Any future implementation must independently satisfy all controls: `TRADING_MODE=live`; `ENABLE_LIVE_TRADING=true`; live-capable adapter; credentials; deterministic risk approval; exact human approval; unexpired approval; unique idempotency; inactive kill switch; fresh market/account state; separately enabled adapter; completed live-execution tests; and unmistakable warning acknowledgement. No model, LLM, prompt, configuration string, or agent can override a failed gate.

Changing these controls requires a security review, ADR, isolated live test suite, broker sandbox evidence, human operations procedure, and an enabled adapter implemented in a separate change. Never test with a real order.

