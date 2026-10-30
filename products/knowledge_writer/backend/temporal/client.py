import asyncio
from uuid import UUID

from django.conf import settings

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from .publish_workflow import PublishInputs, PublishWorkflow

START_TIMEOUT_SECONDS = 2


def publish_workflow_id(task_run_id: UUID) -> str:
    return f"knowledge_writer:publish:{task_run_id}"


def start_publish(task_run_id: UUID, *, team_id: int) -> None:
    asyncio.run(asyncio.wait_for(start_publish_workflow(task_run_id, team_id=team_id), START_TIMEOUT_SECONDS))


async def start_publish_workflow(task_run_id: UUID, *, team_id: int) -> None:
    client = await async_connect()
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
        return
