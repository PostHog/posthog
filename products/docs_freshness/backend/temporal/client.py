from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.docs_freshness.backend.facade.contracts import LandedCommit, PullRequestHead
from products.docs_freshness.backend.temporal.constants import (
    CHECK_LANDED_COMMIT_WORKFLOW,
    CHECK_PULL_REQUEST_HEAD_WORKFLOW,
    WORKFLOW_RETRY_POLICY,
    check_landed_commit_workflow_id,
    check_pull_request_head_workflow_id,
)


async def start_check_pull_request_head(client: Client, head: PullRequestHead) -> None:
    await _start_once(client, CHECK_PULL_REQUEST_HEAD_WORKFLOW, head, check_pull_request_head_workflow_id(head))


@async_to_sync
async def start_check_pull_request_head_workflow(head: PullRequestHead) -> None:
    await start_check_pull_request_head(await async_connect(), head)


@async_to_sync
async def start_check_landed_commit_workflows(commits: list[LandedCommit]) -> None:
    client = await async_connect()
    for commit in commits:
        await _start_once(client, CHECK_LANDED_COMMIT_WORKFLOW, commit, check_landed_commit_workflow_id(commit))


async def _start_once(client: Client, workflow_name: str, workflow_input: object, workflow_id: str) -> None:
    try:
        await client.start_workflow(
            workflow_name,
            workflow_input,
            id=workflow_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.DOCS_FRESHNESS_TASK_QUEUE,
            retry_policy=WORKFLOW_RETRY_POLICY,
        )
    except WorkflowAlreadyStartedError:
        return
