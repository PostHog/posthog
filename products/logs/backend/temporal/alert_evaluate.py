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

    from posthog.temporal.common.utils import close_db_connections

    from products.alerts.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceOutcomeInputs,
    )

WORKFLOW_NAME = "logs-alert-evaluate"

# Above `BATCH_QUERY_BUDGET_SECONDS`, which is above the cap on any one cohort query. With the
# activity below the query, the activity times out while ClickHouse still runs the query, the
# attempt's thread stays on it, and the retry starts an identical query alongside. The ordering is
# asserted by `test_clickhouse_ends_a_slow_cohort_query_before_the_activity_does`.
EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=30)
# How long the activity may wait for a free slot. Temporal bounds an attempt by whichever of the
# two timeouts expires first, so schedule-to-close is derived rather than set: a literal close to
# start-to-close would let queue time shorten the run below the query budget, which is the
# inversion above arriving by another route on exactly the load that causes queueing.
EVALUATE_QUEUE_TOLERANCE = dt.timedelta(seconds=20)
EVALUATE_SCHEDULE_TO_CLOSE = EVALUATE_START_TO_CLOSE + EVALUATE_QUEUE_TOLERANCE
# One attempt. A second is another full query budget spent on a batch whose keys are still due, so
# the next tick reaches it anyway, and holding the key meanwhile blocks its own re-dispatch.
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)
# What the source needs from the platform's `SOURCE_EVALUATION_TIMEOUT`, which has to hold both
# activities and still leave room to start the delivery children.
EVALUATION_BUDGET = EVALUATE_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE


@activity.defn
@close_db_connections
def evaluate_logs_alerts_activity(inputs: SourceEvaluationInputs) -> SourceBatchEvaluation:
    """Sync, so the thread this blocks is a slot Temporal is accounting for. An async activity
    handing the work to its own thread pool releases its slot the moment the activity times out,
    while the thread stays on the query Temporal can no longer see."""
    # Imported in the activity body, not at module scope. The workflow class below forces
    # this module to evaluate inside Temporal's sandbox, which a Django model import trips.
    from products.logs.backend.alert_source_cycle import evaluate_logs_batch

    return evaluate_logs_batch(
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
            retry_policy=RetryPolicy(maximum_attempts=1),
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
                    "alerts-platform-deliver-preview",
                    preview,
                    id=f"alerts-deliver-preview-{preview.evaluation_key}",
                    task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
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
