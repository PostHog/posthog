from datetime import datetime, timedelta

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

from products.signals.backend.facade.constants import SIGNAL_SPEND_RETENTION
from products.signals.backend.models import SignalSpend

_DELETE_BATCH_SIZE = 10_000

CLEANUP_WORKFLOW_NAME = "signal-spend-cleanup"
CLEANUP_SCHEDULE_ID = "signal-spend-cleanup-schedule"
_CLEANUP_TIMEOUT = timedelta(minutes=30)


def _delete_expired_spend_batch(cutoff: datetime) -> int:
    ids = list(
        SignalSpend.objects.unscoped()
        .filter(created_at__lt=cutoff)
        .order_by("created_at")
        .values_list("id", flat=True)[:_DELETE_BATCH_SIZE]
    )
    if not ids:
        return 0
    return SignalSpend.objects.unscoped().filter(id__in=ids).delete()[0]


@activity.defn
async def delete_expired_spend_activity() -> int:
    cutoff = timezone.now() - SIGNAL_SPEND_RETENTION
    deleted = 0
    async with Heartbeater():
        while True:
            batch_deleted = await database_sync_to_async(_delete_expired_spend_batch, thread_sensitive=False)(cutoff)
            if not batch_deleted:
                return deleted
            deleted += batch_deleted


@workflow.defn(name=CLEANUP_WORKFLOW_NAME)
class SignalSpendCleanupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> int:
        return await workflow.execute_activity(
            delete_expired_spend_activity,
            start_to_close_timeout=_CLEANUP_TIMEOUT,
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


async def create_signal_spend_cleanup_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CLEANUP_WORKFLOW_NAME,
            id=CLEANUP_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=_CLEANUP_TIMEOUT,
        ),
        spec=ScheduleSpec(cron_expressions=["45 4 * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, CLEANUP_SCHEDULE_ID):
        await a_update_schedule(client, CLEANUP_SCHEDULE_ID, schedule, keep_paused=True)
    else:
        await a_create_schedule(client, CLEANUP_SCHEDULE_ID, schedule, trigger_immediately=False)
