import time
import asyncio
import dataclasses
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.temporal.common.heartbeat_sync import heartbeat_from_thread, heartbeat_through_loop
    from posthog.temporal.common.utils import asyncify

    from products.tasks.backend.logic.services.orphaned_objects import OrphanedObjectsTotals, clean_orphaned_prefixes
    from products.tasks.backend.logic.services.orphaned_objects_runs import (
        TOTALS_MEMO_KEY,
        WORKFLOW_NAME,
        OrphanedObjectsInput,
    )

HEARTBEAT_INTERVAL_SECONDS = 10


def resume_totals(execute: bool, heartbeat_details: list[object]) -> OrphanedObjectsTotals:
    if not execute or not heartbeat_details:
        return OrphanedObjectsTotals()
    details = heartbeat_details[0]
    assert isinstance(details, dict)
    return OrphanedObjectsTotals(**details)


class ThrottledHeartbeat:
    def __init__(self) -> None:
        self.sent_at = 0.0
        self.sent_totals: OrphanedObjectsTotals | None = None

    def __call__(self, totals: OrphanedObjectsTotals) -> None:
        now = time.monotonic()
        if totals == self.sent_totals and now - self.sent_at < HEARTBEAT_INTERVAL_SECONDS:
            return
        self.sent_at = now
        self.sent_totals = totals
        heartbeat_from_thread(dataclasses.asdict(totals))


@asyncify
def clean(input: OrphanedObjectsInput, start: OrphanedObjectsTotals) -> OrphanedObjectsTotals:
    return clean_orphaned_prefixes(
        bucket=settings.OBJECT_STORAGE_BUCKET,
        kind_names=input.kinds,
        max_prefixes=input.max_prefixes,
        execute=input.execute,
        start=start,
        checkpoint=ThrottledHeartbeat(),
    )


@activity.defn
async def delete_orphaned_task_objects(input: OrphanedObjectsInput) -> OrphanedObjectsTotals:
    start = resume_totals(input.execute, list(activity.info().heartbeat_details))
    with heartbeat_through_loop(asyncio.get_running_loop()):
        return await clean(input, start)


@workflow.defn(name=WORKFLOW_NAME)
class DeleteOrphanedTaskObjectsWorkflow(PostHogWorkflow):
    inputs_cls = OrphanedObjectsInput

    @workflow.run
    async def run(self, input: OrphanedObjectsInput) -> OrphanedObjectsTotals:
        totals = await workflow.execute_activity(
            delete_orphaned_task_objects,
            input,
            start_to_close_timeout=timedelta(hours=12),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=1)),
        )
        workflow.upsert_memo({TOTALS_MEMO_KEY: dataclasses.asdict(totals)})
        return totals
