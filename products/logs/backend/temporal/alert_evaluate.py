"""Temporal wiring for the read-only logs evaluation.

The evaluation itself lives in `products/logs/backend/alert_source_cycle.py`, so it stays a
plain function a test can call without Temporal.
"""

import datetime as dt
import contextlib
import dataclasses

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.sync import database_sync_to_async_pool
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts_platform.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        AlertEventKind,
        PlatformAlertOutcome,
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceOutcomeInputs,
    )
    from products.alerts_platform.backend.facade.temporal import start_deliveries
    from products.logs.backend.alert_signal_emitter import (
        AlertSignalAction,
        PlatformAlertSignal,
        notified_alerts_for_platform,
    )
    from products.logs.backend.temporal.batch_slot import LogsBatchAdmission, LogsBatchSlot

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
# What the source needs from its binding's `evaluation_timeout`, which has to hold the wait, both
# activities, and still leave room to start the delivery and signal children. The wait can run one
# try past its budget, because the last try starts before the budget ends.
EVALUATION_BUDGET = (
    SLOT_WAIT_BUDGET + 2 * TAKE_SLOT_SCHEDULE_TO_CLOSE + EVALUATE_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE
)
# Workflows started before the wait replay the single try inside the evaluation activity.
WAIT_FOR_SLOT_PATCH = "logs-alert-evaluate-wait-for-slot"

SIGNALS_WORKFLOW_NAME = "logs-alert-platform-signals"
# A child workflow with its own budget, so a large batch of signals never competes with the
# evaluation's.
SIGNALS_EXECUTION_TIMEOUT = dt.timedelta(minutes=5)
SIGNALS_START_TO_CLOSE = dt.timedelta(minutes=4)

# Workflows started before the signal step replay without it.
SIGNALS_PATCH = "logs-alert-evaluate-platform-signals"

_SIGNAL_ACTIONS: dict[AlertEventKind, AlertSignalAction] = {
    AlertEventKind.FIRING: "firing",
    AlertEventKind.BROKEN: "broken",
}


@dataclasses.dataclass(frozen=True)
class TakeLogsBatchSlotInputs:
    evaluation: SourceEvaluationInputs
    member: str
    first: bool
    final: bool


@dataclasses.dataclass(frozen=True)
class HeldLogsBatchInputs:
    evaluation: SourceEvaluationInputs
    slot: LogsBatchSlot


@dataclasses.dataclass(frozen=True)
class PlatformSignalInputs:
    team_id: int
    signals: list[PlatformAlertSignal]


def platform_signals(evaluation: SourceBatchEvaluation) -> list[PlatformAlertSignal]:
    """The firings and auto-disables the platform sends a message for, on alerts it owns.

    The logs stack signals the same moments, keyed on a notification going out, which here is a
    delivery that sends messages. An alert the logs stack still owns gets its signal from the logs
    stack, so it is left out. The delivery names the owner and the logs alert id, so the platform's
    outcome contract needs neither.
    """
    announced = {
        delivery.configuration_id: delivery.destination_alert_id
        for delivery in evaluation.deliveries
        if delivery.owned_by_platform and delivery.sends_messages
    }
    signals: list[PlatformAlertSignal] = []
    for outcome in evaluation.outcomes:
        alert_id = announced.get(str(outcome.configuration_id))
        if alert_id is None:
            continue
        signals.extend(
            _signal(
                alert_id,
                outcome,
                _SIGNAL_ACTIONS[group.kind],
                group.value,
                grouping_key=group.grouping_key,
                labels=group.labels,
            )
            for group in outcome.groups
            if group.kind in _SIGNAL_ACTIONS
        )
        # A failed check reports on the outcome and carries no groups, so a broken alert signals from there.
        if outcome.failure is not None and outcome.failure.kind in _SIGNAL_ACTIONS:
            signals.append(_signal(alert_id, outcome, _SIGNAL_ACTIONS[outcome.failure.kind], None))
    return signals


def _signal(
    alert_id: str,
    outcome: PlatformAlertOutcome,
    action: AlertSignalAction,
    value: float | None,
    *,
    grouping_key: str = "",
    labels: dict[str, str] | None = None,
) -> PlatformAlertSignal:
    return PlatformAlertSignal(
        alert_id=alert_id,
        action=action,
        result_count=int(value) if value is not None else None,
        consecutive_failures=outcome.consecutive_failures,
        evaluation_key=outcome.evaluation_key,
        grouping_key=grouping_key,
        labels=labels or {},
    )


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


@activity.defn
@close_db_connections
def take_logs_batch_slot_activity(inputs: TakeLogsBatchSlotInputs) -> LogsBatchAdmission:
    from products.logs.backend.alert_source_cycle import take_logs_batch_slot

    key = inputs.evaluation.batch_key
    return take_logs_batch_slot(
        key.team_id,
        key.slot,
        dt.datetime.fromisoformat(inputs.evaluation.cutoff),
        member=inputs.member,
        first=inputs.first,
        final=inputs.final,
    )


@activity.defn
@close_db_connections
def evaluate_held_logs_batch_activity(inputs: HeldLogsBatchInputs) -> SourceBatchEvaluation:
    """Sync for the same reason as `evaluate_logs_alerts_activity`."""
    from products.logs.backend.alert_source_cycle import evaluate_held_logs_batch

    key = inputs.evaluation.batch_key
    return evaluate_held_logs_batch(
        key.team_id, key.slot, dt.datetime.fromisoformat(inputs.evaluation.cutoff), inputs.slot
    )


@activity.defn
def release_logs_batch_slot_activity(held: LogsBatchSlot) -> None:
    from products.logs.backend.alert_source_cycle import release_logs_batch_slot

    release_logs_batch_slot(held)


@activity.defn
async def emit_platform_alert_signals_activity(inputs: PlatformSignalInputs) -> int:
    """Emits the Self-driving signals for alerts the platform owns. Never raises."""
    # In the body, like the import above, because the workflow's sandbox refuses Django models.
    from products.logs.backend.temporal.activities import emit_notified_alert_signals  # noqa: PLC0415

    notified = await database_sync_to_async_pool(notified_alerts_for_platform)(inputs.team_id, inputs.signals)
    return await emit_notified_alert_signals(notified)


@workflow.defn(name=SIGNALS_WORKFLOW_NAME)
class LogsPlatformAlertSignalsWorkflow(PostHogWorkflow):
    """Emits one evaluation's Self-driving signals, apart from the evaluation itself."""

    inputs_cls = PlatformSignalInputs

    @workflow.run
    async def run(self, inputs: PlatformSignalInputs) -> int:
        # Retried, because each signal carries an idempotency key, so a retry sends only what the
        # failed attempt had not.
        return await workflow.execute_activity(
            emit_platform_alert_signals_activity,
            inputs,
            start_to_close_timeout=SIGNALS_START_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=10)),
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
        if workflow.patched(WAIT_FOR_SLOT_PATCH):
            held = await self._wait_for_slot(inputs)
            if held is None:
                return 0
            try:
                evaluation = await workflow.execute_activity(
                    evaluate_held_logs_batch_activity,
                    HeldLogsBatchInputs(evaluation=inputs, slot=held),
                    start_to_close_timeout=EVALUATE_START_TO_CLOSE,
                    schedule_to_close_timeout=EVALUATE_SCHEDULE_TO_CLOSE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except ActivityError:
                # An evaluation that timed out in the queue never ran its release. The release checks
                # the take's expiry, so it does nothing to a slot an evaluation that did start holds.
                with contextlib.suppress(ActivityError):
                    await workflow.execute_activity(
                        release_logs_batch_slot_activity,
                        held,
                        start_to_close_timeout=TAKE_SLOT_START_TO_CLOSE,
                        schedule_to_close_timeout=TAKE_SLOT_SCHEDULE_TO_CLOSE,
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                raise
        else:
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

        started = await start_deliveries(evaluation.deliveries)

        # After the outcomes are recorded, so a signal never describes a firing that was not saved.
        signals = platform_signals(evaluation)
        if signals and workflow.patched(SIGNALS_PATCH):
            try:
                await workflow.start_child_workflow(
                    LogsPlatformAlertSignalsWorkflow.run,
                    PlatformSignalInputs(team_id=inputs.batch_key.team_id, signals=signals),
                    id=f"{SIGNALS_WORKFLOW_NAME}-{inputs.batch_key.team_id}:{inputs.batch_key.slot}:{inputs.cutoff}",
                    # The delivery queue, so a slow burst of signals never holds evaluation slots.
                    task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=SIGNALS_EXECUTION_TIMEOUT,
                )
            except WorkflowAlreadyStartedError:
                # A re-run of the same evaluation already started its signals.
                pass

        return started

    async def _wait_for_slot(self, inputs: SourceEvaluationInputs) -> LogsBatchSlot | None:
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
                    take_logs_batch_slot_activity,
                    TakeLogsBatchSlotInputs(evaluation=inputs, member=member, first=first, final=final),
                    start_to_close_timeout=TAKE_SLOT_START_TO_CLOSE,
                    schedule_to_close_timeout=TAKE_SLOT_SCHEDULE_TO_CLOSE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except ActivityError:
                # A failed try is a try without a slot. The next one asks again.
                admission = LogsBatchAdmission(due=True)
            if not admission.due:
                return None
            if admission.slot is not None:
                return admission.slot
            if final:
                return None
            first = False
            await workflow.sleep(interval.total_seconds() + workflow.random().uniform(0, SLOT_POLL_JITTER_SECONDS))
            interval = min(interval * 2, SLOT_POLL_MAX_INTERVAL)


SOURCE_EVALUATION_WORKFLOWS = [LogsAlertEvaluateWorkflow]
SOURCE_EVALUATION_ACTIVITIES = [
    evaluate_logs_alerts_activity,
    take_logs_batch_slot_activity,
    evaluate_held_logs_batch_activity,
    release_logs_batch_slot_activity,
]
# Registered on the platform delivery queue, beside the deliveries the evaluation starts.
PLATFORM_SIGNAL_WORKFLOWS = [LogsPlatformAlertSignalsWorkflow]
PLATFORM_SIGNAL_ACTIVITIES = [emit_platform_alert_signals_activity]
