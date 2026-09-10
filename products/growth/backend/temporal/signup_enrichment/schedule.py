"""Temporal Schedules for the signup_enrichment daily jobs.

Each schedule only starts its workflow; pausing one is an instance-setting change, since the
workflow itself re-checks the kill switch and region on every run.
"""

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.growth.backend.temporal.signup_enrichment.harmonic_status_poll import HarmonicStatusPollInputs
from products.growth.backend.temporal.signup_enrichment.reenrichment import IcpReenrichmentSweepInputs

SCHEDULE_ID = "icp-reenrichment-sweep-daily"

# 07:40 UTC daily: off the hour to avoid the shared-queue thundering herd, and adjacent to
# the existing 7am growth/billing batch window so operators find related runs together.
CRON = "40 7 * * *"


def build_icp_reenrichment_sweep_schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "icp-reenrichment-sweep",
            IcpReenrichmentSweepInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.SIGNUP_ENRICHMENT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=[CRON]),
        # A sweep that overruns its slot (huge backlog) must not stack a second run on top.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_icp_reenrichment_sweep_schedule(client: Client) -> None:
    schedule = build_icp_reenrichment_sweep_schedule()
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)


HARMONIC_STATUS_POLL_SCHEDULE_ID = "harmonic-enrichment-status-poll-daily"

# Ahead of the sweep so a same-day stamp is available to it.
HARMONIC_STATUS_POLL_CRON = "40 6 * * *"


def build_harmonic_status_poll_schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "harmonic-enrichment-status-poll",
            HarmonicStatusPollInputs(),
            id=HARMONIC_STATUS_POLL_SCHEDULE_ID,
            task_queue=settings.SIGNUP_ENRICHMENT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=[HARMONIC_STATUS_POLL_CRON]),
        # A run that overruns its slot must not stack a second run of Harmonic calls on top.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_harmonic_status_poll_schedule(client: Client) -> None:
    schedule = build_harmonic_status_poll_schedule()
    if await a_schedule_exists(client, HARMONIC_STATUS_POLL_SCHEDULE_ID):
        await a_update_schedule(client, HARMONIC_STATUS_POLL_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, HARMONIC_STATUS_POLL_SCHEDULE_ID, schedule, trigger_immediately=False)
