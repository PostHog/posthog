"""Temporal wiring for metrics alerts on the shared alerts platform.

The evaluation itself lives in `products/metrics/backend/alerts/evaluation.py`, so it stays a plain
function a test can call without Temporal.
"""

import datetime as dt
import contextlib
import dataclasses
from typing import TYPE_CHECKING

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

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
    from products.metrics.backend.temporal.batch_slot import MetricsBatchAdmission, MetricsBatchSlot

WORKFLOW_NAME = "metrics-alert-evaluate"

# Above `BATCH_QUERY_BUDGET_SECONDS` and `FRESHNESS_QUERY_SECONDS`, so the evaluation stops starting
# queries before the activity times out.
EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=40)
EVALUATE_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=60)
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)
# A batch the pool turns away waits on a workflow timer and tries again, so it runs inside its own
# tick instead of the next. The timer holds no worker slot, which a wait inside the sync activity
# would. A batch still without a slot after the budget keeps its checks due for a later tick. The
# budget is a third of the tick, so a batch let in late still finishes close to its own minute.
# A freed slot goes to whichever batch tries next, not to the one that waited longest.
SLOT_WAIT_BUDGET = dt.timedelta(seconds=20)
# The interval grows from the first to the last value, with jitter, so the batches of one tick do
# not all try again in the same second.
SLOT_POLL_FIRST_INTERVAL = dt.timedelta(seconds=1)
SLOT_POLL_MAX_INTERVAL = dt.timedelta(seconds=4)
SLOT_POLL_JITTER_SECONDS = 0.5
TAKE_SLOT_START_TO_CLOSE = dt.timedelta(seconds=5)
TAKE_SLOT_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=10)
# What the source needs from its binding's `evaluation_timeout`, which has to hold the wait, the
# evaluation and the record, and still leave room to start the delivery children. The wait can run
# one try past its budget, because the last try starts before the budget ends. One record is enough,
# because the evaluation holds a batch to `MAX_BATCH_PAYLOAD_BYTES`, which is also the size of one
# chunk of outcomes.
EVALUATION_BUDGET = (
    SLOT_WAIT_BUDGET + 2 * TAKE_SLOT_SCHEDULE_TO_CLOSE + EVALUATE_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE
)
# Workflows started before the wait replay the single try inside the evaluation activity.
WAIT_FOR_SLOT_PATCH = "metrics-alert-evaluate-wait-for-slot"


@dataclasses.dataclass(frozen=True)
class TakeMetricsBatchSlotInputs:
    evaluation: SourceEvaluationInputs
    member: str
    first: bool
    final: bool


@dataclasses.dataclass(frozen=True)
class HeldMetricsBatchInputs:
    evaluation: SourceEvaluationInputs
    slot: MetricsBatchSlot


@activity.defn
@close_db_connections
def evaluate_metrics_alerts_activity(inputs: SourceEvaluationInputs) -> SourceBatchEvaluation:
    """Sync, so the thread this blocks is a slot Temporal is accounting for."""
    # Imported in the body, because the workflow below makes this module load inside Temporal's
    # sandbox, which refuses a Django model import.
    from products.metrics.backend.alerts.evaluation import evaluate_metrics_alert_batch  # noqa: PLC0415

    return evaluate_metrics_alert_batch(
        inputs.batch_key.team_id, inputs.batch_key.slot, dt.datetime.fromisoformat(inputs.cutoff)
    )


@activity.defn
@close_db_connections
def take_metrics_batch_slot_activity(inputs: TakeMetricsBatchSlotInputs) -> MetricsBatchAdmission:
    from products.metrics.backend.alerts.evaluation import take_metrics_batch_slot  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    return take_metrics_batch_slot(
        key.team_id,
        key.slot,
        dt.datetime.fromisoformat(inputs.evaluation.cutoff),
        member=inputs.member,
        first=inputs.first,
        final=inputs.final,
    )


@activity.defn
@close_db_connections
def evaluate_held_metrics_batch_activity(inputs: HeldMetricsBatchInputs) -> SourceBatchEvaluation:
    """Sync for the same reason as `evaluate_metrics_alerts_activity`."""
    from products.metrics.backend.alerts.evaluation import evaluate_held_metrics_batch  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    return evaluate_held_metrics_batch(
        key.team_id, key.slot, dt.datetime.fromisoformat(inputs.evaluation.cutoff), inputs.slot
    )


@activity.defn
def release_metrics_batch_slot_activity(held: MetricsBatchSlot) -> None:
    from products.metrics.backend.alerts.evaluation import release_metrics_batch_slot  # noqa: PLC0415

    release_metrics_batch_slot(held)


@workflow.defn(name=WORKFLOW_NAME)
class MetricsAlertEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key, records what it decided, and starts the deliveries it asked for."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # One attempt. The evaluation writes nothing, so a lost attempt leaves the checks due and
        # the next tick reads them again.
        if workflow.patched(WAIT_FOR_SLOT_PATCH):
            held = await self._wait_for_slot(inputs)
            if held is None:
                return 0
            try:
                evaluation = await workflow.execute_activity(
                    evaluate_held_metrics_batch_activity,
                    HeldMetricsBatchInputs(evaluation=inputs, slot=held),
                    start_to_close_timeout=EVALUATE_START_TO_CLOSE,
                    schedule_to_close_timeout=EVALUATE_SCHEDULE_TO_CLOSE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except ActivityError:
                # An evaluation that timed out in the queue never ran its release. The release checks
                # the take's expiry, so it does nothing to a slot an evaluation that did start holds.
                with contextlib.suppress(ActivityError):
                    await workflow.execute_activity(
                        release_metrics_batch_slot_activity,
                        held,
                        start_to_close_timeout=TAKE_SLOT_START_TO_CLOSE,
                        schedule_to_close_timeout=TAKE_SLOT_SCHEDULE_TO_CLOSE,
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                raise
        else:
            evaluation = await workflow.execute_activity(
                evaluate_metrics_alerts_activity,
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

    async def _wait_for_slot(self, inputs: SourceEvaluationInputs) -> MetricsBatchSlot | None:
        """Tries for a pool slot until one frees or the wait budget ends. None when the batch has
        nothing left to evaluate, or when it still has no slot, which leaves its checks due."""
        # From the workflow, so it is the same on replay and on every retry of a try.
        member = f"{inputs.batch_key.team_id}:{inputs.batch_key.slot}:{workflow.uuid4().hex}"
        deadline = workflow.now() + SLOT_WAIT_BUDGET
        interval = SLOT_POLL_FIRST_INTERVAL
        first = True
        while True:
            final = workflow.now() >= deadline
            try:
                admission = await workflow.execute_activity(
                    take_metrics_batch_slot_activity,
                    TakeMetricsBatchSlotInputs(evaluation=inputs, member=member, first=first, final=final),
                    start_to_close_timeout=TAKE_SLOT_START_TO_CLOSE,
                    schedule_to_close_timeout=TAKE_SLOT_SCHEDULE_TO_CLOSE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except ActivityError:
                # A failed try is a try without a slot. The next one asks again.
                admission = MetricsBatchAdmission(due=True)
            if not admission.due:
                return None
            if admission.slot is not None:
                return admission.slot
            if final:
                return None
            first = False
            await workflow.sleep(interval.total_seconds() + workflow.random().uniform(0, SLOT_POLL_JITTER_SECONDS))
            interval = min(interval * 2, SLOT_POLL_MAX_INTERVAL)


METRICS_ALERT_EVALUATION_WORKFLOWS = [MetricsAlertEvaluateWorkflow]
METRICS_ALERT_EVALUATION_ACTIVITIES: list[ActivityDefinition] = [
    evaluate_metrics_alerts_activity,
    take_metrics_batch_slot_activity,
    evaluate_held_metrics_batch_activity,
    release_metrics_batch_slot_activity,
]
