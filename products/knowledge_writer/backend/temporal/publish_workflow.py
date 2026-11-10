from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from ..logic.pull_requests import open_or_join_pull_request, settle_publication
from ..logic.records import PUBLICATION_LEASE

PUBLISH_ATTEMPTS = 3
PUBLISH_RETRY_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True)
class PublishInputs:
    task_run_id: str
    team_id: int


@activity.defn
@close_db_connections
async def publish_docs_pull_request_activity(inputs: PublishInputs) -> None:
    async with Heartbeater():
        await database_sync_to_async(open_or_join_pull_request, thread_sensitive=False)(
            UUID(inputs.task_run_id), team_id=inputs.team_id
        )


@dataclass(frozen=True)
class SettleInputs:
    task_run_id: str
    team_id: int
    has_failed: bool


@activity.defn
@close_db_connections
async def settle_publication_activity(inputs: SettleInputs) -> None:
    await database_sync_to_async(settle_publication, thread_sensitive=False)(
        UUID(inputs.task_run_id), team_id=inputs.team_id, has_failed=inputs.has_failed
    )


@workflow.defn(name="knowledge-writer-publish")
class PublishWorkflow:
    @workflow.run
    async def run(self, inputs: PublishInputs) -> None:
        has_failed = True
        try:
            await workflow.execute_activity(
                publish_docs_pull_request_activity,
                inputs,
                schedule_to_close_timeout=PUBLICATION_LEASE - timedelta(minutes=5),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(initial_interval=PUBLISH_RETRY_INTERVAL, maximum_attempts=PUBLISH_ATTEMPTS),
            )
            has_failed = False
        finally:
            await workflow.execute_activity(
                settle_publication_activity,
                SettleInputs(task_run_id=inputs.task_run_id, team_id=inputs.team_id, has_failed=has_failed),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(initial_interval=PUBLISH_RETRY_INTERVAL, maximum_attempts=PUBLISH_ATTEMPTS),
            )
