# Backtesting

`run_backtest` is research-only and never calls broker code. It selects score-threshold candidates, caps positions, enters at the next session open with slippage, exits only after the configured holding period, charges entry/exit commissions, and caps quantity by next-session volume participation. This avoids same-close execution, cost-free turnover, and impossible unlimited fills.

Reports state the period, total/benchmark return, maximum drawdown, turnover, hit rate, average exposure, trade count, assumptions, and limitations. The caller must provide point-in-time universe and adjusted-price policy; survivorship and corporate-action limitations are never hidden. Combined decision-policy signals should be tested separately from raw model scores.
