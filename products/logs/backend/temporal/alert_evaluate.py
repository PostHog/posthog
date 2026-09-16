"""Temporal wiring for the read-only logs evaluation.

The evaluation itself lives in `products/logs/backend/alert_source_cycle.py`, so it stays a
plain function a test can call without Temporal.
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

    from products.alerts.backend.facade.contracts import AlertDeliveryPreview, SourceEvaluationInputs

WORKFLOW_NAME = "logs-alert-evaluate"


@activity.defn
async def evaluate_logs_alerts_activity(inputs: SourceEvaluationInputs) -> tuple[AlertDeliveryPreview, ...]:
    # Imported in the activity body, not at module scope. The workflow class below forces
    # this module to evaluate inside Temporal's sandbox, which a Django model import trips.
    from products.logs.backend.alert_source_cycle import evaluate_logs_configurations

    return await database_sync_to_async_pool(evaluate_logs_configurations)(
        inputs.configuration_ids, dt.datetime.fromisoformat(inputs.cutoff)
    )


@workflow.defn(name=WORKFLOW_NAME)
class LogsAlertEvaluateWorkflow(PostHogWorkflow):
    """Evaluates the configurations its dispatcher handed over, then previews one delivery
    per notification. Writes nothing: the production logs fleet owns these alerts."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        previews = await workflow.execute_activity(
            evaluate_logs_alerts_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=25),
            schedule_to_close_timeout=dt.timedelta(seconds=35),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # The evaluation key names the alert and its window, so a re-run of the same occasion
        # reuses these ids. A reused id raises, so one already-started preview must not stop
        # the rest.
        results = await asyncio.gather(
            *(
                workflow.start_child_workflow(
                    "alerts-product-deliver-preview",
                    preview,
                    id=f"alerts-deliver-preview-{preview.evaluation_key}",
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
        return len(previews)


SOURCE_EVALUATION_WORKFLOWS = [LogsAlertEvaluateWorkflow]
SOURCE_EVALUATION_ACTIVITIES = [evaluate_logs_alerts_activity]
