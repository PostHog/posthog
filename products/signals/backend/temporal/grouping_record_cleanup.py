"""Daily deletion of expired SignalGroupingRecord rows."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.signals.backend.models import SignalGroupingRecord

# A record only has to live while grouping can retry its batch. A row deleted while its batch
# still retries lets that retry count the signal again, so keep a wide margin over the retry window.
GROUPING_RECORD_RETENTION = timedelta(days=7)
_DELETE_BATCH_SIZE = 10_000

CLEANUP_WORKFLOW_NAME = "signal-grouping-record-cleanup"
CLEANUP_SCHEDULE_ID = "signal-grouping-record-cleanup-schedule"
_CLEANUP_TIMEOUT = timedelta(minutes=30)


def delete_expired_grouping_records() -> int:
    cutoff = timezone.now() - GROUPING_RECORD_RETENTION
    deleted = 0
    while True:
        ids = list(
            SignalGroupingRecord.objects.unscoped()
            .filter(created_at__lt=cutoff)
            .values_list("id", flat=True)[:_DELETE_BATCH_SIZE]
        )
        if not ids:
            return deleted
        deleted += SignalGroupingRecord.objects.unscoped().filter(id__in=ids).delete()[0]


@activity.defn
async def delete_expired_grouping_records_activity() -> int:
    async with Heartbeater():
        return await database_sync_to_async(delete_expired_grouping_records, thread_sensitive=False)()


@workflow.defn(name=CLEANUP_WORKFLOW_NAME)
class SignalGroupingRecordCleanupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> int:
        return await workflow.execute_activity(
            delete_expired_grouping_records_activity,
            start_to_close_timeout=_CLEANUP_TIMEOUT,
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


async def create_signal_grouping_record_cleanup_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CLEANUP_WORKFLOW_NAME,
            id=CLEANUP_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=_CLEANUP_TIMEOUT,
        ),
        spec=ScheduleSpec(cron_expressions=["30 4 * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, CLEANUP_SCHEDULE_ID):
        await a_update_schedule(client, CLEANUP_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, CLEANUP_SCHEDULE_ID, schedule, trigger_immediately=False)
