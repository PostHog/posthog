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

SIGNALS_SCOUT_COORDINATOR_SCHEDULE_ID = "signals-scout-coordinator-schedule"
SIGNALS_SCOUT_COORDINATOR_WORKFLOW_NAME = "run-signals-scout-coordinator"


async def create_signals_scout_coordinator_schedule(client: Client) -> None:
    """Create or update the schedule that drives the Signals agent coordinator.

    The coordinator runs on the existing signals task queue (currently
    `VIDEO_EXPORT_TASK_QUEUE`, shared with the rest of the signals temporal worker).
    `ScheduleOverlapPolicy.SKIP` is a defense-in-depth guard against pathologically
    slow ticks; the coordinator itself dispatches children fire-and-forget so its
    lifetime is normally seconds and overlap should never fire in practice.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SIGNALS_SCOUT_COORDINATOR_WORKFLOW_NAME,
            asdict(CoordinatorWorkflowInput()),
            id=SIGNALS_SCOUT_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
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
