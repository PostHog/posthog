from dataclasses import dataclass

from temporalio import activity

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.exceptions import GitHubRateLimitedError, ProcessTaskTransientError
from products.tasks.backend.temporal.babysit_pr.snapshot import PRSnapshot
from products.tasks.backend.temporal.metrics import increment_pr_babysit_snapshot
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.activities import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    DEFAULT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS,
    load_wakeable_pull_request,
    merge_queue_push_would_eject,
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
