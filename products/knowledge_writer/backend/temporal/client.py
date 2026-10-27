import asyncio

from django.conf import settings

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from .merge_workflow import MergeCheckInputs, MergeCheckWorkflow

START_TIMEOUT_SECONDS = 2


def merge_check_workflow_id(commit_sha: str) -> str:
    return f"knowledge_writer:repo_merge:{commit_sha}"


def start_merge_check(commit_sha: str, *, team_id: int) -> None:
    asyncio.run(asyncio.wait_for(start_merge_check_workflow(commit_sha, team_id=team_id), START_TIMEOUT_SECONDS))


async def start_merge_check_workflow(commit_sha: str, *, team_id: int) -> None:
    client = await async_connect()
    try:
        await client.start_workflow(
            MergeCheckWorkflow.run,
            MergeCheckInputs(commit_sha=commit_sha, team_id=team_id),
            id=merge_check_workflow_id(commit_sha),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except WorkflowAlreadyStartedError:
        return
