from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.exceptions import GitHubRateLimitedError, ProcessTaskTransientError
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.babysit_pr.snapshot import PRSnapshot
from products.tasks.backend.temporal.metrics import increment_pr_babysit_snapshot
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.activities import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    DEFAULT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS,
    get_github_integration,
    get_user_github_integration,
)


@dataclass(frozen=True)
class GetPrBabysitSnapshotInput:
    context: TaskProcessingContext


@activity.defn(name="get_pr_babysit_snapshot")
@close_db_connections
def get_pr_babysit_snapshot(input: GetPrBabysitSnapshotInput) -> PRSnapshot | None:
    ctx = input.context
    with log_activity_execution(
        "get_pr_babysit_snapshot",
        **ctx.to_log_context(),
    ):
        if not ctx.has_github_credentials:
            return None

        try:
            task_run = TaskRun.objects.get(id=ctx.run_id)
        except TaskRun.DoesNotExist:
            activity.logger.warning("get_pr_babysit_snapshot_task_run_not_found", run_id=ctx.run_id)
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
                "get_pr_babysit_snapshot_github_integration_not_found",
                github_integration_id=ctx.github_integration_id,
                github_user_integration_id=ctx.github_user_integration_id,
            )
            return None

        try:
            raw = github_integration.get_pull_request_babysit_snapshot(pr_url)
        except (GitHubRateLimitError, GitHubEgressBudgetExhausted) as e:
            retry_after = getattr(e, "retry_after", None) or DEFAULT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS
            raise GitHubRateLimitedError(
                f"GitHub rate limited PR babysit snapshot for URL {pr_url}; retrying in {retry_after}s",
                context={
                    "pr_url": pr_url,
                    "github_integration_id": ctx.github_integration_id,
                    "github_user_integration_id": ctx.github_user_integration_id,
                },
                retry_after=retry_after,
            )
        except Exception as e:
            raise ProcessTaskTransientError(
                f"Failed to fetch PR babysit snapshot from GitHub for URL {pr_url}",
                context={
                    "pr_url": pr_url,
                    "github_integration_id": ctx.github_integration_id,
                    "github_user_integration_id": ctx.github_user_integration_id,
                },
                cause=e,
            )

        if not raw.get("success"):
            activity.logger.warning(
                "get_pr_babysit_snapshot_failed",
                run_id=ctx.run_id,
                pr_url=pr_url,
                error=raw.get("error"),
            )
            increment_pr_babysit_snapshot("unavailable")
            return None

        snapshot = PRSnapshot.from_raw(raw, pr_url)
        increment_pr_babysit_snapshot("fetched", pr_state=snapshot.pr_state)
        return snapshot
