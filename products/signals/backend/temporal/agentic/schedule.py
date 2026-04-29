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

from products.signals.backend.temporal.agentic.agent_coordinator import (
    COORDINATOR_INTERVAL_MINUTES,
    DEFAULT_STAGGER_MINUTES,
    CoordinatorWorkflowInput,
)

SIGNALS_AGENT_COORDINATOR_SCHEDULE_ID = "signals-agent-coordinator-schedule"
SIGNALS_AGENT_COORDINATOR_WORKFLOW_NAME = "run-signals-agent-coordinator"


async def create_signals_agent_coordinator_schedule(client: Client) -> None:
    """Create or update the hourly schedule that drives the Signals agent coordinator.

    The coordinator runs on the existing signals task queue (currently
    `VIDEO_EXPORT_TASK_QUEUE`, shared with the rest of the signals temporal worker).
    `ScheduleOverlapPolicy.SKIP` ensures a slow batch never collides with itself —
    a tick that takes longer than the interval just suppresses the next one.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SIGNALS_AGENT_COORDINATOR_WORKFLOW_NAME,
            asdict(CoordinatorWorkflowInput(stagger_minutes=DEFAULT_STAGGER_MINUTES)),
            id=SIGNALS_AGENT_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SIGNALS_AGENT_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, SIGNALS_AGENT_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            SIGNALS_AGENT_COORDINATOR_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )
