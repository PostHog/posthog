"""Temporal wiring for the read-only metrics evaluation on the shared alerts platform.

The evaluation itself lives in `products/metrics/backend/alert_source_cycle.py`, so it stays a
plain function a test can call without Temporal. The shape copies the logs source: one sync
activity that reads and decides, the platform's own activity that records, and one abandoned
delivery child per notification.
"""

import asyncio
import datetime as dt
from collections.abc import Callable
from typing import Any

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

WORKFLOW_NAME = "metrics-alert-evaluate"

# Above `BATCH_QUERY_BUDGET_SECONDS`, which is above the cap on any one query, so ClickHouse ends
# an overrunning query before the activity does. With the activity below the query, the attempt's
# thread stays on a query Temporal can no longer see and the retry starts an identical one.
EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=30)
# Derived rather than literal: a schedule-to-close close to start-to-close lets queue time shorten
# the run below the query budget on exactly the load that causes queueing.
EVALUATE_QUEUE_TOLERANCE = dt.timedelta(seconds=20)
EVALUATE_SCHEDULE_TO_CLOSE = EVALUATE_START_TO_CLOSE + EVALUATE_QUEUE_TOLERANCE
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)
# What this source needs from the platform's `SOURCE_EVALUATION_TIMEOUT`.
EVALUATION_BUDGET = EVALUATE_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE


@activity.defn
@close_db_connections
def evaluate_metrics_alerts_activity(inputs: SourceEvaluationInputs) -> SourceBatchEvaluation:
    """Sync, so the thread this blocks is a slot Temporal is accounting for."""
    # Imported in the activity body: the workflow class below makes Temporal's sandbox evaluate
    # this module, and a Django model import trips it.
    from products.metrics.backend.alert_source_cycle import evaluate_metrics_batch  # noqa: PLC0415

    return evaluate_metrics_batch(
        inputs.batch_key.team_id, inputs.batch_key.slot, dt.datetime.fromisoformat(inputs.cutoff)
    )


@workflow.defn(name=WORKFLOW_NAME)
class MetricsAlertEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key, records what it decided, then previews one delivery per
    notification. Writes only the shared platform's own rows."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        evaluation = await workflow.execute_activity(
            evaluate_metrics_alerts_activity,
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
        # reuses these ids and one already-started preview must not stop the rest.
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


SOURCE_EVALUATION_WORKFLOWS: list[type[PostHogWorkflow]] = [MetricsAlertEvaluateWorkflow]
SOURCE_EVALUATION_ACTIVITIES: list[Callable[..., Any]] = [evaluate_metrics_alerts_activity]
