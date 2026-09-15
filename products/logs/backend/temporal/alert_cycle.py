"""Temporal wiring for the read-only logs evaluation cycle.

The evaluation itself lives in `products/logs/backend/alert_source_cycle.py`, so it stays a
plain function that a test can call without Temporal.
"""

import asyncio
import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.sync import database_sync_to_async_pool

    from products.alerts.backend.facade.contracts import AlertDeliveryPreview, SourceCycleInputs, SourceCycleResult

WORKFLOW_NAME = "logs-alert-source-cycle"


@activity.defn
async def evaluate_due_logs_alerts_activity() -> tuple[AlertDeliveryPreview, ...]:
    # Imported in the activity body, not at module scope. The workflow class below forces
    # this module to evaluate inside Temporal's sandbox, which a Django model import trips.
    from products.logs.backend.alert_source_cycle import evaluate_due_logs_alerts

    return await database_sync_to_async_pool(evaluate_due_logs_alerts)()


@workflow.defn(name=WORKFLOW_NAME)
class LogsAlertSourceCycleWorkflow(PostHogWorkflow):
    """Evaluates every due logs alert, then starts one delivery preview per notification."""

    inputs_cls = SourceCycleInputs

    @workflow.run
    async def run(self, inputs: SourceCycleInputs) -> SourceCycleResult:
        previews = await workflow.execute_activity(
            evaluate_due_logs_alerts_activity,
            start_to_close_timeout=dt.timedelta(minutes=2),
            schedule_to_close_timeout=dt.timedelta(minutes=4),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # A re-run of the same occasion reuses these ids, and Temporal raises on a reused
        # id, so one already-started preview must not stop the rest.
        results = await asyncio.gather(
            *(
                workflow.start_child_workflow(
                    "alerts-product-deliver-preview",
                    preview,
                    id=f"alerts-deliver-preview-{preview.alert_id}-{preview.evaluation_key}",
                    task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=dt.timedelta(minutes=1),
                )
                for preview in previews
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, WorkflowAlreadyStartedError):
                continue
            if isinstance(result, BaseException):
                raise result

        return SourceCycleResult(
            source_kind=inputs.source_kind,
            notifications_dispatched=len(previews),
        )


SOURCE_CYCLE_WORKFLOWS = [LogsAlertSourceCycleWorkflow]
SOURCE_CYCLE_ACTIVITIES = [evaluate_due_logs_alerts_activity]
