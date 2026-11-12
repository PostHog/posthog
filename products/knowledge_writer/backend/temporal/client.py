import asyncio
from uuid import UUID

from django.conf import settings

import structlog
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from ...merge_check.sources import LandedChange
from .merge_workflow import MergeCheckInputs, MergeCheckWorkflow
from .publish_workflow import PublishInputs, PublishWorkflow

logger = structlog.get_logger(__name__)

START_TIMEOUT_SECONDS = 2


def publish_workflow_id(task_run_id: UUID) -> str:
    return f"knowledge_writer:publish:{task_run_id}"


def start_publish(task_run_id: UUID, *, team_id: int) -> None:
    asyncio.run(asyncio.wait_for(start_publish_workflow(task_run_id, team_id=team_id), START_TIMEOUT_SECONDS))


async def start_publish_workflow(task_run_id: UUID, *, team_id: int) -> None:
    client = await async_connect()
    log_context = {"task_run_id": str(task_run_id), "team_id": team_id}
    try:
        await client.start_workflow(
            PublishWorkflow.run,
            PublishInputs(task_run_id=str(task_run_id), team_id=team_id),
            id=publish_workflow_id(task_run_id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except WorkflowAlreadyStartedError:
        logger.info("knowledge_writer_publish_already_ran", **log_context)
        return
    logger.info("knowledge_writer_publish_requested", **log_context)


def merge_check_workflow_id(commit_sha: str) -> str:
    return f"knowledge_writer:repo_merge:{commit_sha}"


def start_merge_check(change: LandedChange, *, team_id: int, installation_id: str | None) -> None:
    asyncio.run(
        asyncio.wait_for(
            start_merge_check_workflow(change, team_id=team_id, installation_id=installation_id),
            START_TIMEOUT_SECONDS,
        )
    )


async def start_merge_check_workflow(
    change: LandedChange, *, team_id: int, installation_id: str | None = None, client: Client | None = None
) -> None:
    temporal = client or await async_connect()
    log_context = {
        "commit_sha": change.after,
        "repository": change.repository,
        "pull_request_number": change.pull_request_number,
        "team_id": team_id,
        "is_webhook_delivery": installation_id is not None,
    }
    try:
        await temporal.start_workflow(
            MergeCheckWorkflow.run,
            MergeCheckInputs(
                commit_sha=change.after,
                team_id=team_id,
                repository=change.repository,
                pull_request_number=change.pull_request_number,
                installation_id=installation_id,
            ),
            id=merge_check_workflow_id(change.after),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except WorkflowAlreadyStartedError:
        logger.info("knowledge_writer_merge_check_already_ran", **log_context)
        return
    logger.info("knowledge_writer_merge_check_requested", **log_context)
