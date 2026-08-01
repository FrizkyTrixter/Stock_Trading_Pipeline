"""First-class reconciliation that reports rather than silently correcting differences."""

from .types import BrokerOrder, ReconciliationReport


def reconcile(
    local_orders: tuple[BrokerOrder, ...], broker_orders: tuple[BrokerOrder, ...]
) -> ReconciliationReport:
    local = {order.broker_order_id: order for order in local_orders}
    remote = {order.broker_order_id: order for order in broker_orders}
    common = set(local) & set(remote)
    discrepancies = []
    for order_id in common:
        if local[order_id].state != remote[order_id].state:
            discrepancies.append(f"status_mismatch:{order_id}")
        if local[order_id].filled_quantity != remote[order_id].filled_quantity:
            discrepancies.append(f"filled_quantity_mismatch:{order_id}")
    return ReconciliationReport(
        matched_order_ids=tuple(sorted(common)),
        broker_only_order_ids=tuple(sorted(set(remote) - set(local))),
        local_only_order_ids=tuple(sorted(set(local) - set(remote))),
        discrepancies=tuple(discrepancies),
        status="matched" if not discrepancies and set(local) == set(remote) else "mismatch",
    )
