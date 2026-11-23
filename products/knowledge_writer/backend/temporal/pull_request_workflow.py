from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings

import structlog
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from ..logic.pull_requests import settle_pull_request

logger = structlog.get_logger(__name__)

STALE_AFTER = timedelta(days=7)
WINDOWS_PER_RUN = 10
CLOSED_SIGNAL = "closed"
SETTLE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(minutes=1), maximum_interval=timedelta(hours=1), maximum_attempts=20
)


@dataclass(frozen=True)
class PullRequestInputs:
    team_id: int
    repository: str
    pull_request_number: int


@dataclass(frozen=True)
class SettlePullRequestInputs:
    team_id: int
    repository: str
    pull_request_number: int
    timed_out: bool


def pull_request_workflow_id(repository: str, pull_request_number: int) -> str:
    owner, name = repository.lower().split("/", 1)
    return f"knowledge-writer-pr-{owner}.{name}-{pull_request_number}"


@activity.defn
@close_db_connections
async def settle_pull_request_activity(inputs: SettlePullRequestInputs) -> bool:
    return await database_sync_to_async(settle_pull_request, thread_sensitive=False)(
        inputs.team_id, inputs.repository, inputs.pull_request_number, timed_out=inputs.timed_out
    )


@workflow.defn(name="knowledge-writer-pull-request")
class WriterPullRequestWorkflow:
    def __init__(self) -> None:
        self.closed_signal_count = 0
        self.settled_signal_count = 0

    @workflow.signal(name=CLOSED_SIGNAL)
    def closed(self) -> None:
        self.closed_signal_count += 1

    @workflow.run
    async def run(self, inputs: PullRequestInputs) -> None:
        for _window in range(WINDOWS_PER_RUN):
            timed_out = not await self.wait_for_closed_signal()
            self.settled_signal_count = self.closed_signal_count
            if await self.settle(inputs, timed_out=timed_out):
                return
        workflow.continue_as_new(inputs)

    async def settle(self, inputs: PullRequestInputs, *, timed_out: bool) -> bool:
        try:
            return await workflow.execute_activity(
                settle_pull_request_activity,
                SettlePullRequestInputs(
                    team_id=inputs.team_id,
                    repository=inputs.repository,
                    pull_request_number=inputs.pull_request_number,
                    timed_out=timed_out,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=SETTLE_RETRY_POLICY,
            )
        except ActivityError as error:
            workflow.logger.warning(
                "knowledge_writer_pull_request_settle_failed",
                exc_info=error,
                extra={
                    "team_id": inputs.team_id,
                    "repository": inputs.repository,
                    "pull_request_number": inputs.pull_request_number,
                    "timed_out": timed_out,
                },
            )
            return False

    async def wait_for_closed_signal(self) -> bool:
        try:
            await workflow.wait_condition(
                lambda: self.closed_signal_count > self.settled_signal_count, timeout=STALE_AFTER
            )
        except TimeoutError:
            return False
        return True


async def start_pull_request_workflow(client: Client, inputs: PullRequestInputs) -> None:
    log_context = {
        "team_id": inputs.team_id,
        "repository": inputs.repository,
        "pull_request_number": inputs.pull_request_number,
    }
    try:
        await client.start_workflow(
            WriterPullRequestWorkflow.run,
            inputs,
            id=pull_request_workflow_id(inputs.repository, inputs.pull_request_number),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except WorkflowAlreadyStartedError:
        logger.info("knowledge_writer_pull_request_watch_already_ran", **log_context)
        return
    logger.info("knowledge_writer_pull_request_watch_started", **log_context)
