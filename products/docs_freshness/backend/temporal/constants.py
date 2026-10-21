from datetime import timedelta

from temporalio.common import RetryPolicy

from products.docs_freshness.backend.facade.contracts import PullRequestHead

CHECK_PULL_REQUEST_HEAD_WORKFLOW = "docs-freshness-check-pull-request-head"

CHECK_HEAD_TIMEOUT = timedelta(minutes=20)
RECORD_VERDICT_TIMEOUT = timedelta(minutes=5)
DURABLE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=600),
    maximum_attempts=6,
)
WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)


def check_pull_request_head_workflow_id(head: PullRequestHead) -> str:
    return f"docs-freshness-{head.pr_number}-{head.head_sha}"
