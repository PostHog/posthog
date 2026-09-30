import asyncio
import datetime as dt

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
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from .workflows import WORKFLOW_NAME

SCHEDULE_ID = "security-sync-access-rules-schedule"
SYNC_NOW_WORKFLOW_ID = "security-sync-access-rules-now"
EXECUTION_TIMEOUT = dt.timedelta(minutes=4)


async def create_sync_access_rules_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=dt.timedelta(minutes=5))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=True)


def start_sync_now() -> None:
    """Starts a pull at once. A pull that is already running absorbs the request."""
    temporal = sync_connect()
    asyncio.run(
        temporal.start_workflow(
            WORKFLOW_NAME,
            id=SYNC_NOW_WORKFLOW_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=EXECUTION_TIMEOUT,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    )
