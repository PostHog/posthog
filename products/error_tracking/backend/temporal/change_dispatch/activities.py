from datetime import timedelta

from django.db import close_old_connections

import structlog
from temporalio import activity

from products.error_tracking.backend.temporal.change_dispatch.types import ChangeDispatchInputs, ChangeDispatchResult

logger = structlog.get_logger(__name__)


@activity.defn
def dispatch_issue_changes_activity(inputs: ChangeDispatchInputs) -> ChangeDispatchResult:
    # The dispatch logic imports lifecycle_events, which imports this temporal package, so a
    # module-level import here makes a cycle whenever the logic module is imported first.
    from products.error_tracking.backend.logic.change_dispatch import dispatch_pending_changes  # noqa: PLC0415

    close_old_connections()
    outcome = dispatch_pending_changes(time_budget=timedelta(seconds=inputs.time_budget_seconds))
    logger.info(
        "error_tracking.change_dispatch.complete",
        dispatched=outcome.dispatched,
        delivered=outcome.delivered,
        undelivered=outcome.undelivered,
        dropped=outcome.dropped,
    )
    return ChangeDispatchResult(
        dispatched=outcome.dispatched,
        delivered=outcome.delivered,
        undelivered=outcome.undelivered,
        dropped=outcome.dropped,
    )
