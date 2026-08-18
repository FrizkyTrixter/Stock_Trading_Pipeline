# Deterministic risk and allocation

`CapitalAllocationPolicy` applies the configured model threshold, maximum positions, maximum
position weight/notional, and cash reserve. `StopLossPolicy` applies the configured percentage to
every holding each completed session. Whole-share quantities round down. The LLM never supplies
dollar values, quantities, exits, ledger mutations, or overrides.
