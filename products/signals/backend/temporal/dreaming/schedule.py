"""Schedule registration for the nightly Dreaming Agent coordinator."""

from __future__ import annotations

from dataclasses import asdict

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.signals.backend.temporal.dreaming.coordinator import DreamingCoordinatorInput

DREAMING_COORDINATOR_SCHEDULE_ID = "dreaming-coordinator-schedule"
DREAMING_COORDINATOR_WORKFLOW_NAME = "run-dreaming-coordinator"

# Low-traffic hour: 08:00 UTC. Late night in the Americas, early morning in Europe — the
# nightly "organize the project while you sleep" cadence.
DREAMING_COORDINATOR_HOUR_UTC = 8


async def create_dreaming_coordinator_schedule(client: Client) -> None:
    """Create or update the nightly schedule that drives the Dreaming Agent coordinator.

    Runs on the shared signals task queue. ``ScheduleOverlapPolicy.SKIP`` drops a tick rather
    than queueing it if a prior coordinator is somehow still running — the coordinator's
    lifetime is normally seconds (fire-and-forget child dispatch), so overlap should never
    fire in practice.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            DREAMING_COORDINATOR_WORKFLOW_NAME,
            asdict(DreamingCoordinatorInput()),
            id=DREAMING_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Nightly at 08:00 UTC",
                    hour=[ScheduleRange(start=DREAMING_COORDINATOR_HOUR_UTC, end=DREAMING_COORDINATOR_HOUR_UTC)],
                    minute=[ScheduleRange(start=0, end=0)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, DREAMING_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, DREAMING_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            DREAMING_COORDINATOR_SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )
