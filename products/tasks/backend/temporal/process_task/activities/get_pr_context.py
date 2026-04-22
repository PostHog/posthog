from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.models import Integration
from posthog.models.integration import GitHubIntegration

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.process_task.activities import TaskProcessingContext


@dataclass
class GetPrContextInput:
    context: TaskProcessingContext


@dataclass
class GetPrContextOutput:
    pr_url: str
    pr_state: str
    fingerprint: str


def compute_pr_fingerprint(pr: dict[str, Any]) -> str:
    """Compute a fingerprint for a PR based on its URL and updated_at timestamp."""
    import hashlib

    pr_url = pr.get("url", "")
    updated_at = pr.get("updated_at", "")
    fingerprint_source = f"{pr_url}|{updated_at}"
    return hashlib.sha256(fingerprint_source.encode()).hexdigest()


def get_github_integration(github_integration_id: int) -> GitHubIntegration:
    integration = Integration.objects.get(id=github_integration_id)
    github_integration = GitHubIntegration(integration)

    if github_integration.access_token_expired():
        github_integration.refresh_access_token()

    return github_integration


@activity.defn
def get_pr_context(input: GetPrContextInput):
    ctx = input.context
    if not ctx.github_integration_id:
        raise TaskInvalidStateError(
            "GitHub integration ID is missing from context",
            context={"run_id": ctx.run_id, "github_integration_id": ctx.github_integration_id},
            cause=RuntimeError("GitHub integration ID missing"),
        )
    """Get PR context for a task run, including PR URL, repository, and allowed domains."""
    try:
        task_run = TaskRun.objects.get(id=ctx.run_id)
    except TaskRun.DoesNotExist:
        raise TaskNotFoundError(
            f"TaskRun with id {ctx.run_id} not found",
            context={"run_id": ctx.run_id},
            cause=RuntimeError("TaskRun not found"),
        )
    pr_url = (task_run.output or {}).get("pr_url")
    if not pr_url:
        return None
    try:
        github_integration = get_github_integration(ctx.github_integration_id)
    except ObjectDoesNotExist:
        raise TaskInvalidStateError(
            f"GitHub integration with id {ctx.github_integration_id} not found",
            context={"github_integration_id": ctx.github_integration_id},
            cause=RuntimeError("GitHub integration not found"),
        )

    try:
        pull_request = github_integration.get_pull_request_from_url(pr_url)  # Validate PR URL and permissions
        fingerprint = compute_pr_fingerprint(pull_request)
    except Exception as e:
        raise TaskInvalidStateError(
            f"Failed to fetch PR details from GitHub for URL {pr_url}",
            context={"pr_url": pr_url, "github_integration_id": ctx.github_integration_id},
            cause=e,
        )

    return GetPrContextOutput(
        pr_url=pr_url,
        pr_state=pull_request.get("state", "unknown"),
        fingerprint=fingerprint,
    )
