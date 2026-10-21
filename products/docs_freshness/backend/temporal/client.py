from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.docs_freshness.backend.facade.contracts import PullRequestHead
from products.docs_freshness.backend.temporal.constants import (
    CHECK_PULL_REQUEST_HEAD_WORKFLOW,
    WORKFLOW_RETRY_POLICY,
    check_pull_request_head_workflow_id,
)


@async_to_sync
async def start_check_pull_request_head_workflow(head: PullRequestHead) -> None:
    client = await async_connect()
    try:
        await client.start_workflow(
            CHECK_PULL_REQUEST_HEAD_WORKFLOW,
            head,
            id=check_pull_request_head_workflow_id(head),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.DOCS_FRESHNESS_TASK_QUEUE,
            retry_policy=WORKFLOW_RETRY_POLICY,
        )
    except WorkflowAlreadyStartedError:
        return
