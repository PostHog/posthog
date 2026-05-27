"""Daily schedule registration for the Replay Vision cleanup sweep."""

from django.conf import settings

from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import SearchAttributePair, TypedSearchAttributes

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.replay_vision.backend.temporal.cleanup_sweep.constants import (
    SCHEDULE_ID,
    SCHEDULE_INTERVAL,
    SCHEDULE_TYPE,
    WORKFLOW_EXECUTION_TIMEOUT,
    WORKFLOW_ID,
    WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.cleanup_sweep.types import CleanupSweepInputs


async def create_replay_vision_cleanup_sweep_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            CleanupSweepInputs(),
            id=WORKFLOW_ID,
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        # SKIP keeps a slow sweep from piling up onto the next day's run.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    search_attributes = TypedSearchAttributes(
        search_attributes=[SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=SCHEDULE_TYPE)]
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule, search_attributes=search_attributes)
    else:
        # trigger_immediately=False: this is a destructive sweep; a first-run at deploy time could delete
        # the full accumulated backlog with no human in the loop. The next regular fire is good enough.
        await a_create_schedule(
            client,
            SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
            search_attributes=search_attributes,
        )
