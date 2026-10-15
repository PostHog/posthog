"""Temporal wiring for the read-only logs evaluation.

The evaluation itself lives in `products/logs/backend/alert_source_cycle.py`, so it stays a
plain function a test can call without Temporal.
"""

import datetime as dt
import dataclasses

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.sync import database_sync_to_async_pool
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts_platform.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        AlertEventKind,
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
# What the source needs from its binding's `evaluation_timeout`, which has to hold both
# activities and still leave room to start the delivery and signal children.
EVALUATION_BUDGET = EVALUATE_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE

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
        if str(outcome.configuration_id) not in announced:
            continue
        # A failed check reports on the outcome and carries no groups, so a broken alert signals from there.
        verdicts: list[tuple[AlertEventKind, float | None]] = [(group.kind, group.value) for group in outcome.groups]
        if outcome.failure is not None:
            verdicts.append((outcome.failure.kind, None))
        signals.extend(
            PlatformAlertSignal(
                alert_id=announced[str(outcome.configuration_id)],
                action=_SIGNAL_ACTIONS[kind],
                result_count=int(value) if value is not None else None,
                consecutive_failures=outcome.consecutive_failures,
                evaluation_key=outcome.evaluation_key,
            )
            for kind, value in verdicts
            if kind in _SIGNAL_ACTIONS
        )
    return signals


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


SOURCE_EVALUATION_WORKFLOWS = [LogsAlertEvaluateWorkflow]
SOURCE_EVALUATION_ACTIVITIES = [evaluate_logs_alerts_activity]
# Registered on the platform delivery queue, beside the deliveries the evaluation starts.
PLATFORM_SIGNAL_WORKFLOWS = [LogsPlatformAlertSignalsWorkflow]
PLATFORM_SIGNAL_ACTIVITIES = [emit_platform_alert_signals_activity]
