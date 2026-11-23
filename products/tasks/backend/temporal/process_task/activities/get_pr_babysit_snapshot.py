from dataclasses import dataclass
from typing import Any

from temporalio import activity

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.integrations import IntegrationNotFound
from posthog.models.integration import GitLabIntegrationError
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.constants import CI_STATUSES, PR_STATES
from products.tasks.backend.exceptions import GitHubRateLimitedError, ProcessTaskTransientError
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.babysit_pr.gitlab import GitLabMergeRequestClient
from products.tasks.backend.temporal.babysit_pr.snapshot import PRSnapshot
from products.tasks.backend.temporal.metrics import increment_pr_babysit_snapshot
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.activities import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    DEFAULT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS,
    load_wakeable_pr_url,
    load_wakeable_pull_request,
    merge_queue_push_would_eject,
)


@dataclass(frozen=True)
class GetPrBabysitSnapshotInput:
    context: TaskProcessingContext


def load_gitlab_merge_request(
    ctx: TaskProcessingContext, pr_url: str, activity_name: str
) -> GitLabMergeRequestClient | None:
    client = None
    if ctx.repository_integration_id is not None:
        try:
            client = GitLabMergeRequestClient.load(ctx.team_id, ctx.repository_integration_id, pr_url)
        except IntegrationNotFound:
            pass
    if client is None:
        activity.logger.warning(
            f"{activity_name}_gitlab_merge_request_unavailable",
            extra={"run_id": ctx.run_id, "repository_integration_id": ctx.repository_integration_id},
        )
    return client


def _persist_merge_request_state(run_id: str, snapshot: PRSnapshot) -> None:
    """GitLab sends PostHog no merge request webhooks, so this poll is what keeps the task's MR state current."""
    updates: dict[str, Any] = {}
    if snapshot.pr_state in PR_STATES:
        updates["pr_state"] = snapshot.pr_state
    if snapshot.pr_state == "merged":
        updates["pr_merged"] = True
    # A terminal snapshot reads no pipeline, so its "none" must not replace the last real CI status.
    if not snapshot.is_terminal and snapshot.ci_status in CI_STATUSES:
        updates["ci_status"] = snapshot.ci_status
    if not updates:
        return
    try:
        TaskRun.update_output_atomic(run_id, updates=updates)
    except Exception:
        activity.logger.warning("get_pr_babysit_snapshot_persist_failed", exc_info=True)


def _get_gitlab_snapshot(ctx: TaskProcessingContext) -> PRSnapshot | None:
    pr_url = load_wakeable_pr_url(ctx, "get_pr_babysit_snapshot")
    if pr_url is None:
        return None
    client = load_gitlab_merge_request(ctx, pr_url, "get_pr_babysit_snapshot")
    if client is None:
        return None
    error_context = {"pr_url": pr_url, "repository_integration_id": ctx.repository_integration_id}
    try:
        raw = client.get_babysit_snapshot()
    except GitLabIntegrationError as e:
        if not e.transient:
            activity.logger.warning(
                "get_pr_babysit_snapshot_failed", extra={"run_id": ctx.run_id, "pr_url": pr_url, "error": str(e)}
            )
            increment_pr_babysit_snapshot("unavailable")
            return None
        raise ProcessTaskTransientError(
            f"GitLab is unavailable for merge request {pr_url}", context=error_context, cause=e
        )
    except Exception as e:
        raise ProcessTaskTransientError(
            f"Failed to fetch merge request babysit snapshot from GitLab for URL {pr_url}",
            context=error_context,
            cause=e,
        )
    if not raw.get("success"):
        activity.logger.warning(
            "get_pr_babysit_snapshot_failed",
            extra={"run_id": ctx.run_id, "pr_url": pr_url, "error": raw.get("error")},
        )
        increment_pr_babysit_snapshot("unavailable")
        return None
    snapshot = PRSnapshot.from_raw(raw, pr_url)
    _persist_merge_request_state(ctx.run_id, snapshot)
    increment_pr_babysit_snapshot("fetched", pr_state=snapshot.pr_state)
    return snapshot


@activity.defn(name="get_pr_babysit_snapshot")
@close_db_connections
def get_pr_babysit_snapshot(input: GetPrBabysitSnapshotInput) -> PRSnapshot | None:
    ctx = input.context
    with log_activity_execution(
        "get_pr_babysit_snapshot",
        **ctx.to_log_context(),
    ):
        if ctx.has_gitlab_credentials:
            return _get_gitlab_snapshot(ctx)

        target = load_wakeable_pull_request(ctx, "get_pr_babysit_snapshot")
        if target is None:
            return None
        pr_url, github_integration = target.pr_url, target.github_integration

        try:
            raw = github_integration.get_pull_request_babysit_snapshot(pr_url)
            # A closed PR ends the loop anyway, so a failed queue read must not fail its last tick.
            if raw.get("success") and raw.get("state") not in ("closed", "merged"):
                raw["merge_queue_push_would_eject"] = merge_queue_push_would_eject(github_integration, pr_url)
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
                extra={"run_id": ctx.run_id, "pr_url": pr_url, "error": raw.get("error")},
            )
            increment_pr_babysit_snapshot("unavailable")
            return None

        snapshot = PRSnapshot.from_raw(raw, pr_url)
        increment_pr_babysit_snapshot("fetched", pr_state=snapshot.pr_state)
        return snapshot
