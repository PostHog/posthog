"""Temporal wiring for warehouse alerts on the shared alerts platform.

The evaluation itself lives in `products/warehouse_sources/backend/sync_alerts/evaluation.py`, so it
stays a plain function a test can call without Temporal. One workflow serves both warehouse kinds,
because the dispatcher passes the kind in its inputs.
"""

import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts_platform.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceOutcomeInputs,
    )
    from products.alerts_platform.backend.facade.payload import outcome_chunks
    from products.alerts_platform.backend.facade.temporal import start_deliveries

WORKFLOW_NAME = "warehouse-alert-evaluate"

EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=20)
EVALUATE_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=30)
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)


@activity.defn
@close_db_connections
def evaluate_warehouse_alerts_activity(inputs: SourceEvaluationInputs) -> SourceBatchEvaluation:
    """Sync, so the thread this blocks is a slot Temporal is accounting for."""
    # Imported in the body, because the workflow below makes this module load inside Temporal's
    # sandbox, which refuses a Django model import.
    from products.warehouse_sources.backend.sync_alerts.evaluation import (  # noqa: PLC0415
        evaluate_warehouse_alert_batch,
    )

    return evaluate_warehouse_alert_batch(
        inputs.source, inputs.batch_key.team_id, inputs.batch_key.slot, dt.datetime.fromisoformat(inputs.cutoff)
    )


@workflow.defn(name=WORKFLOW_NAME)
class WarehouseAlertEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key, records what it decided, and starts the deliveries it asked for."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # One attempt. The evaluation writes nothing, so a lost attempt leaves the checks due and
        # the next tick reads them again.
        evaluation = await workflow.execute_activity(
            evaluate_warehouse_alerts_activity,
            inputs,
            start_to_close_timeout=EVALUATE_START_TO_CLOSE,
            schedule_to_close_timeout=EVALUATE_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        started = 0
        for chunk in outcome_chunks(evaluation.outcomes):
            await workflow.execute_activity(
                RECORD_OUTCOMES_ACTIVITY,
                SourceOutcomeInputs(team_id=inputs.batch_key.team_id, cutoff=inputs.cutoff, outcomes=chunk),
                start_to_close_timeout=RECORD_START_TO_CLOSE,
                schedule_to_close_timeout=RECORD_SCHEDULE_TO_CLOSE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # Started only after the record, because a delivery reads the history row the record writes.
            recorded = {str(outcome.configuration_id) for outcome in chunk}
            started += await start_deliveries(
                [delivery for delivery in evaluation.deliveries if delivery.configuration_id in recorded]
            )
        return started


WAREHOUSE_ALERT_EVALUATION_WORKFLOWS = [WarehouseAlertEvaluateWorkflow]
WAREHOUSE_ALERT_EVALUATION_ACTIVITIES = [evaluate_warehouse_alerts_activity]
