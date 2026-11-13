import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from django.conf import settings

import structlog
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from ...merge_check.sources import LandedChange
from ..adapters.repo_merge import pull_request_key
from ..facade.contracts import DocsCommandRequest
from ..facade.enums import DocsRequestSource
from .merge_workflow import ADD_DOCS_CHECK_WAITER_SIGNAL, MergeCheckInputs, MergeCheckWorkflow
from .publish_workflow import PublishInputs, PublishWorkflow

logger = structlog.get_logger(__name__)

START_TIMEOUT_SECONDS = 2


def publish_workflow_id(task_run_id: UUID) -> str:
    return f"knowledge_writer:publish:{task_run_id}"


def run_with_start_timeout(start: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(start, START_TIMEOUT_SECONDS))


def start_publish(task_run_id: UUID, *, team_id: int) -> None:
    run_with_start_timeout(start_publish_workflow(task_run_id, team_id=team_id))


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
    run_with_start_timeout(start_merge_check_workflow(change, team_id=team_id, installation_id=installation_id))


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


def docs_check_id(repository: str, pull_request_number: int) -> str:
    return f"knowledge_writer:command_tag:{pull_request_key(repository, pull_request_number)}"


def start_command_check(command: DocsCommandRequest, *, team_id: int, waiter_id: str | None) -> None:
    run_with_start_timeout(start_command_check_workflow(command, team_id=team_id, waiter_id=waiter_id))


async def start_command_check_workflow(command: DocsCommandRequest, *, team_id: int, waiter_id: str | None) -> None:
    temporal = await async_connect()
    await temporal.start_workflow(
        MergeCheckWorkflow.run,
        MergeCheckInputs(
            commit_sha=None,
            team_id=team_id,
            repository=command.repository,
            pull_request_number=command.pull_request_number,
            origin=DocsRequestSource.COMMAND_TAG,
            requested_by=command.requested_by,
            requested_by_user_id=command.requested_by_user_id,
            note=command.note,
        ),
        id=docs_check_id(command.repository, command.pull_request_number),
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        start_signal=None if waiter_id is None else ADD_DOCS_CHECK_WAITER_SIGNAL,
        start_signal_args=[] if waiter_id is None else [waiter_id],
    )
    logger.info(
        "knowledge_writer_command_check_requested",
        repository=command.repository,
        pull_request_number=command.pull_request_number,
        team_id=team_id,
    )
