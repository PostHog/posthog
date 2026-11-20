from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from ..logic.intake import drain_legacy_held_requests, relaunch_run_without_base
from ..logic.pull_requests import PublishedPullRequest, open_pull_request_for_run, settle_publication
from .pull_request_workflow import PullRequestInputs, start_pull_request_workflow

PUBLISH_ATTEMPTS = 3
PUBLISH_RETRY_INTERVAL = timedelta(minutes=1)
PUBLISH_DEADLINE = timedelta(minutes=25)
HELD_REQUESTS_REMOVED_PATCH = "knowledge-writer-held-requests-removed"


@dataclass(frozen=True)
class PublishInputs:
    task_run_id: str
    team_id: int


@activity.defn
@close_db_connections
async def publish_docs_pull_request_activity(inputs: PublishInputs) -> None:
    async with Heartbeater():
        is_relaunched = await database_sync_to_async(relaunch_run_without_base, thread_sensitive=False)(
            UUID(inputs.task_run_id), team_id=inputs.team_id
        )
        if is_relaunched:
            return
        published = await database_sync_to_async(open_pull_request_for_run, thread_sensitive=False)(
            UUID(inputs.task_run_id),
            team_id=inputs.team_id,
            is_final_attempt=activity.info().attempt >= PUBLISH_ATTEMPTS,
        )
    if published is None:
        return
    await watch_published_pull_request(published, team_id=inputs.team_id)


async def watch_published_pull_request(published: PublishedPullRequest, *, team_id: int) -> None:
    watched = PullRequestInputs(team_id=team_id, repository=published.repository, pull_request_number=published.number)
    try:
        await start_pull_request_workflow(activity.client(), watched)
    except Exception as error:
        if activity.info().attempt < PUBLISH_ATTEMPTS:
            raise
        capture_exception(
            error,
            {"team_id": team_id, "repository": published.repository, "pull_request_number": published.number},
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


# Legacy activity replays executions started before held requests were removed; delete once none remain open.
@activity.defn
async def start_held_requests_activity() -> None:
    await database_sync_to_async(drain_legacy_held_requests, thread_sensitive=False)()


async def run_legacy_held_requests_activity() -> None:
    if workflow.patched(HELD_REQUESTS_REMOVED_PATCH):
        return
    await workflow.execute_activity(
        start_held_requests_activity,
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


@workflow.defn(name="knowledge-writer-start-held-requests")
class StartHeldRequestsWorkflow:
    @workflow.run
    async def run(self) -> None:
        await run_legacy_held_requests_activity()


@workflow.defn(name="knowledge-writer-publish")
class PublishWorkflow:
    @workflow.run
    async def run(self, inputs: PublishInputs) -> None:
        has_failed = True
        try:
            await workflow.execute_activity(
                publish_docs_pull_request_activity,
                inputs,
                schedule_to_close_timeout=PUBLISH_DEADLINE,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(initial_interval=PUBLISH_RETRY_INTERVAL, maximum_attempts=PUBLISH_ATTEMPTS),
            )
            has_failed = False
        finally:
            try:
                await workflow.execute_activity(
                    settle_publication_activity,
                    SettleInputs(task_run_id=inputs.task_run_id, team_id=inputs.team_id, has_failed=has_failed),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(
                        initial_interval=PUBLISH_RETRY_INTERVAL, maximum_attempts=PUBLISH_ATTEMPTS
                    ),
                )
            finally:
                await run_legacy_held_requests_activity()
