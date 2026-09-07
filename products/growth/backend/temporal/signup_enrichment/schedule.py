"""The Temporal Schedule for the daily ICP re-enrichment sweep.

Registered from posthog/temporal/schedule.py, so every deploy upserts it. The schedule only
starts the workflow; the sweep re-checks the kill switch, region, and cap on every run, so
pausing it is an instance-setting change, not a Temporal operation.
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
