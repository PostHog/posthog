from datetime import timedelta

from temporalio.common import RetryPolicy

from products.docs_freshness.backend.facade.contracts import LandedCommit, PullRequestHead

CHECK_PULL_REQUEST_HEAD_WORKFLOW = "docs-freshness-check-pull-request-head"
CHECK_LANDED_COMMIT_WORKFLOW = "docs-freshness-check-landed-commit"

CHECK_HEAD_TIMEOUT = timedelta(minutes=20)
RECORD_VERDICT_TIMEOUT = timedelta(minutes=5)
START_LANDED_CHECK_TIMEOUT = timedelta(minutes=5)
DURABLE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=600),
    maximum_attempts=6,
)
WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)


def check_pull_request_head_workflow_id(head: PullRequestHead) -> str:
    return f"docs-freshness-{head.pr_number}-{head.head_sha}"


def check_landed_commit_workflow_id(commit: LandedCommit) -> str:
    return f"docs-freshness-landed-{commit.merge_sha}"
