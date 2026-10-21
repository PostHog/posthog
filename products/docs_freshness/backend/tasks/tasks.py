from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from posthog.celery_queues import CeleryQueue
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models.github_integration_base import GitHubIntegrationError

from products.docs_freshness.backend.facade.contracts import DocsFreshnessCheckError, MergeRefMissing, PullRequestHead
from products.docs_freshness.backend.logic import impact_check
from products.tasks.backend.facade.sandbox import SandboxExecutionError, SandboxProvisionError, SandboxTimeoutError


@shared_task(
    bind=True,
    name="products.docs_freshness.backend.tasks.check_pull_request_head",
    queue=CeleryQueue.LONG_RUNNING.value,
    ignore_result=True,
    autoretry_for=(
        DocsFreshnessCheckError,
        GitHubRateLimitError,
        EgressBudgetExhausted,
        GitHubIntegrationError,
        SandboxProvisionError,
        SandboxExecutionError,
        SandboxTimeoutError,
        SoftTimeLimitExceeded,
    ),
    retry_backoff=60,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=20 * 60,
    time_limit=25 * 60,
)
def check_pull_request_head(self: Task, repository: str, pr_number: int, head_sha: str) -> None:
    head = PullRequestHead(repository=repository, pr_number=pr_number, head_sha=head_sha)
    try:
        impact_check.check_pull_request_head(head)
    except MergeRefMissing:
        if self.request.retries < self.max_retries:
            raise
        impact_check.record_unmergeable_verdict(head)
