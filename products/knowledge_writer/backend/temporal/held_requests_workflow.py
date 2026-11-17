from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from ..logic import intake


@activity.defn
@close_db_connections
async def start_held_requests_activity() -> None:
    await database_sync_to_async(intake.sweep_held_requests, thread_sensitive=False)()


async def start_held_requests() -> None:
    await workflow.execute_activity(
        start_held_requests_activity,
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


@workflow.defn(name="knowledge-writer-start-held-requests")
class StartHeldRequestsWorkflow:
    @workflow.run
    async def run(self) -> None:
        await start_held_requests()
