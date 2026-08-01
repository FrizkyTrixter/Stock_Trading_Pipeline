# ADR 0005: Broker abstraction and disabled live adapter

Status: accepted, 2026-08-01.

All broker interaction goes through a capability-declaring adapter called only by `ExecutionService`. The deterministic fake is the implemented adapter; live is a disabled skeleton. This supports reliable state-machine tests while making accidental real submission impossible in the supplied code.

