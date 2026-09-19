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

    from products.alerts.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceOutcomeInputs,
    )

WORKFLOW_NAME = "logs-alert-evaluate"

# The dispatcher gives this workflow 40 seconds. Both activities have to fit inside that with
# room to start the delivery children, so a slow evaluation cannot leave the write no budget and
# hand the whole batch back to the next tick.
EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=20)
EVALUATE_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=24)
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)


@activity.defn
async def evaluate_logs_alerts_activity(inputs: SourceEvaluationInputs) -> SourceBatchEvaluation:
    # Imported in the activity body, not at module scope. The workflow class below forces
    # this module to evaluate inside Temporal's sandbox, which a Django model import trips.
    from products.logs.backend.alert_source_cycle import evaluate_logs_batch

    return await database_sync_to_async_pool(evaluate_logs_batch)(
        inputs.batch_key.team_id, inputs.batch_key.slot, dt.datetime.fromisoformat(inputs.cutoff)
    )


@workflow.defn(name=WORKFLOW_NAME)
class LogsAlertEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key, records what it decided, then previews one delivery per
    notification. Writes only the shared platform's own rows: the production logs fleet owns
    the logs tables."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # The evaluation writes nothing, so a lost attempt costs its queries and the retry reads
        # the same still-due batch. Its result reaches history before the write below runs.
        evaluation = await workflow.execute_activity(
            evaluate_logs_alerts_activity,
            inputs,
            start_to_close_timeout=EVALUATE_START_TO_CLOSE,
            schedule_to_close_timeout=EVALUATE_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if evaluation.outcomes:
            await workflow.execute_activity(
                RECORD_OUTCOMES_ACTIVITY,
                SourceOutcomeInputs(
                    team_id=inputs.batch_key.team_id,
                    cutoff=inputs.cutoff,
                    outcomes=evaluation.outcomes,
                ),
                start_to_close_timeout=RECORD_START_TO_CLOSE,
                schedule_to_close_timeout=RECORD_SCHEDULE_TO_CLOSE,
                retry_policy=RetryPolicy(maximum_attempts=3),
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
                for preview in evaluation.previews
            ),
            return_exceptions=True,
        )
        started = 0
        for result in results:
            if isinstance(result, WorkflowAlreadyStartedError):
                continue
            if isinstance(result, BaseException):
                raise result
            started += 1
        return started


SOURCE_EVALUATION_WORKFLOWS = [LogsAlertEvaluateWorkflow]
SOURCE_EVALUATION_ACTIVITIES = [evaluate_logs_alerts_activity]
