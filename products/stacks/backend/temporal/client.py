"""Starts stack runs from Django code. The worker on the stacks queue runs them."""

from uuid import UUID

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.stacks.backend.temporal.types import StackRunInput

DIFF_WORKFLOW = "stacks-diff"
PUSH_WORKFLOW = "stacks-push"


async def _start(workflow_name: str, workflow_id: str, run_input: StackRunInput) -> None:
    client = await async_connect()
    await client.start_workflow(
        workflow_name,
        run_input,
        id=workflow_id,
        # Each diff and each push attempt has its own id, so a second start of one is a duplicate and raises
        # WorkflowAlreadyStartedError, which the caller treats as already running.
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        task_queue=settings.STACKS_TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )


@async_to_sync
async def start_diff_workflow(*, team_id: int, diff_id: UUID) -> None:
    await _start(DIFF_WORKFLOW, f"stacks-diff-{diff_id}", StackRunInput(team_id=team_id, diff_id=str(diff_id)))


@async_to_sync
async def start_push_workflow(*, team_id: int, diff_id: UUID, attempt_id: UUID) -> None:
    await _start(
        PUSH_WORKFLOW,
        f"stacks-push-{attempt_id}",
        StackRunInput(team_id=team_id, diff_id=str(diff_id), attempt_id=str(attempt_id)),
    )
