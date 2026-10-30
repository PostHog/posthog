from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from ..logic.pull_requests import open_or_join_pull_request

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


@workflow.defn(name="knowledge-writer-publish")
class PublishWorkflow:
    @workflow.run
    async def run(self, inputs: PublishInputs) -> None:
        await workflow.execute_activity(
            publish_docs_pull_request_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(initial_interval=PUBLISH_RETRY_INTERVAL, maximum_attempts=PUBLISH_ATTEMPTS),
        )
