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

from products.stacks.backend.temporal.types import StackCleanupInput

SCHEDULE_ID = "stacks-cleanup-schedule"
# Short enough that an abandoned push is marked uncertain soon after its lease expires, and that a saved diff's
# bytes outlive its push deadline by at most this long.
SCHEDULE_INTERVAL = timedelta(minutes=10)


async def create_stacks_cleanup_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "stacks-cleanup", StackCleanupInput(), id=SCHEDULE_ID, task_queue=settings.STACKS_TASK_QUEUE
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)], jitter=timedelta(minutes=2)),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
