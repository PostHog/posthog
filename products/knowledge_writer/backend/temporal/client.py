import asyncio

from django.conf import settings

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from .backstop import PUSH_SEEN, VERDICT_RECORDED, MergeBackstopInputs, MergeBackstopWorkflow

__all__ = ["PUSH_SEEN", "VERDICT_RECORDED", "signal_merge_backstop"]

SIGNAL_TIMEOUT_SECONDS = 2


def backstop_workflow_id(commit_sha: str) -> str:
    return f"knowledge_writer:repo_merge:{commit_sha}"


def signal_merge_backstop(commit_sha: str, *, team_id: int, signal: str) -> None:
    asyncio.run(
        asyncio.wait_for(start_or_signal_backstop(commit_sha, team_id=team_id, signal=signal), SIGNAL_TIMEOUT_SECONDS)
    )


async def start_or_signal_backstop(commit_sha: str, *, team_id: int, signal: str) -> None:
    client = await async_connect()
    try:
        await client.start_workflow(
            MergeBackstopWorkflow.run,
            MergeBackstopInputs(commit_sha=commit_sha, team_id=team_id),
            id=backstop_workflow_id(commit_sha),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            start_signal=signal,
        )
    except WorkflowAlreadyStartedError:
        return
