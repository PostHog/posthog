"""Schedule registration for the headless Signals agent coordinator."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.signals.backend.temporal.agentic.scout_coordinator import (
    COORDINATOR_INTERVAL_MINUTES,
    CoordinatorWorkflowInput,
)
from products.signals.backend.temporal.agentic.scout_suggestions import (
    SUGGESTIONS_COORDINATOR_INTERVAL_MINUTES,
    SUGGESTIONS_COORDINATOR_SCHEDULE_ID,
    SUGGESTIONS_COORDINATOR_WORKFLOW_NAME,
    SuggestionsCoordinatorInput,
)

SIGNALS_SCOUT_COORDINATOR_SCHEDULE_ID = "signals-scout-coordinator-schedule"
SIGNALS_SCOUT_COORDINATOR_WORKFLOW_NAME = "run-signals-scout-coordinator"


async def create_signals_scout_coordinator_schedule(client: Client) -> None:
    """Create or update the schedule that drives the Signals agent coordinator.

    The coordinator runs on the existing signals task queue (currently
    `VIDEO_EXPORT_TASK_QUEUE`, shared with the rest of the signals temporal worker).
    `ScheduleOverlapPolicy.SKIP` is a defense-in-depth guard against pathologically
    slow ticks. The coordinator paces its fan-out across a smear window well under the tick,
    and `execution_timeout` caps it at one whole interval, so a tick that somehow burns its
    activity retry budget is killed rather than left running to starve the next tick under
    `SKIP` — its undispatched scouts stay unstamped and re-dispatch on that next tick.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SIGNALS_SCOUT_COORDINATOR_WORKFLOW_NAME,
            asdict(CoordinatorWorkflowInput()),
            id=SIGNALS_SCOUT_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SIGNALS_SCOUT_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, SIGNALS_SCOUT_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            SIGNALS_SCOUT_COORDINATOR_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )


async def create_scout_suggestions_coordinator_schedule(client: Client) -> None:
    """Create or update the schedule driving the pre-computed scout suggestions coordinator.

    Its own schedule (not a branch of the scout coordinator) so it can be paused independently;
    the `signals-scout-suggestions` flag payload is the softer switch (`enabled: false` plans
    nothing). Same task queue and overlap posture as the scout coordinator.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SUGGESTIONS_COORDINATOR_WORKFLOW_NAME,
            asdict(SuggestionsCoordinatorInput()),
            id=SUGGESTIONS_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            # One whole interval, like the scout coordinator: `SKIP` means an execution that never
            # ends would silently starve every later tick.
            execution_timeout=timedelta(minutes=SUGGESTIONS_COORDINATOR_INTERVAL_MINUTES),
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=SUGGESTIONS_COORDINATOR_INTERVAL_MINUTES))]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SUGGESTIONS_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, SUGGESTIONS_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SUGGESTIONS_COORDINATOR_SCHEDULE_ID, schedule, trigger_immediately=False)
