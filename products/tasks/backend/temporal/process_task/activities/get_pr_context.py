import hashlib
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.models import Integration
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import log_activity_execution
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
    """Fingerprint the actionable state of a PR for the CI follow-up loop.

    Keyed on the signals that mean the agent has real work to do — PR state, the
    CI check rollup, the review decision, and the number of unresolved review
    threads — never on ``updated_at``. GitHub bumps ``updated_at`` on any PR
    activity (comments, labels, reviews, the bot's own pushes), so hashing it
    re-poked the agent for every one of those long after the PR was opened.
    Hashing the fields below re-fires the follow-up only when CI, the review
    decision, or the open-thread count actually change.
    """
    fingerprint_source = "|".join(
        str(pr.get(key, "")) for key in ("url", "state", "ci_status", "review_decision", "unresolved_threads")
    )
    return hashlib.sha256(fingerprint_source.encode()).hexdigest()


def get_github_integration(github_integration_id: int) -> GitHubIntegration:
    integration = Integration.objects.get(id=github_integration_id)
    github_integration = GitHubIntegration(integration)

    if github_integration.access_token_expired():
        github_integration.refresh_access_token()

    return github_integration


def get_user_github_integration(github_user_integration_id: str) -> UserGitHubIntegration:
    return UserGitHubIntegration(UserIntegration.objects.get(id=github_user_integration_id))


@activity.defn
@close_db_connections
def get_pr_context(input: GetPrContextInput) -> GetPrContextOutput | None:
    """Get PR context for a task run, including PR URL, repository, and allowed domains."""
    ctx = input.context
    with log_activity_execution(
        "get_pr_context",
        **ctx.to_log_context(),
    ):
        if not ctx.has_github_credentials:
            return None

        try:
            task_run = TaskRun.objects.get(id=ctx.run_id)
        except TaskRun.DoesNotExist:
            activity.logger.warning("get_pr_context_task_run_not_found", run_id=ctx.run_id)
            return None

        pr_url = (task_run.output or {}).get("pr_url")
        if not pr_url:
            return None

        try:
            github_integration: GitHubIntegration | UserGitHubIntegration
            if ctx.github_integration_id:
                github_integration = get_github_integration(ctx.github_integration_id)
            else:
                github_integration = get_user_github_integration(str(ctx.github_user_integration_id))
        except ObjectDoesNotExist:
            activity.logger.warning(
                "get_pr_context_github_integration_not_found",
                github_integration_id=ctx.github_integration_id,
                github_user_integration_id=ctx.github_user_integration_id,
            )
            return None

        try:
            # Snapshot (GraphQL) over the plain REST fetch: it carries the CI rollup,
            # review decision, and unresolved-thread count the fingerprint keys on, so
            # the follow-up loop can tell real CI/review changes from noise like comments.
            pull_request = github_integration.get_pull_request_snapshot(pr_url)  # Validate PR URL and permissions
            if not pull_request.get("success"):
                return None
            fingerprint = compute_pr_fingerprint(pull_request)
        except Exception as e:
            raise TaskInvalidStateError(
                f"Failed to fetch PR details from GitHub for URL {pr_url}",
                context={
                    "pr_url": pr_url,
                    "github_integration_id": ctx.github_integration_id,
                    "github_user_integration_id": ctx.github_user_integration_id,
                },
                cause=e,
            )

        return GetPrContextOutput(
            pr_url=pr_url,
            pr_state=pull_request.get("state", "unknown"),
            fingerprint=fingerprint,
        )
