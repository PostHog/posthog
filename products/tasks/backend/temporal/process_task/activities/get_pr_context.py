import hashlib
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.models import Integration
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.exceptions import ProcessTaskTransientError
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
    # Defaults keep replay of pre-rollout activity results deserializable.
    ci_status: str = "none"
    changes_requested: bool = False


def is_pr_actionable(pr: GetPrContextOutput) -> bool:
    """Whether a changed PR snapshot warrants waking the agent.

    Only failing CI or a changes-requested review gives the agent real work to
    do. Waking it for a green, pending, or check-less PR produces a "nothing to
    report" turn that spams the originating Slack thread and burns one of the
    limited CI follow-up repetitions. Pending needs no special handling: the
    head SHA and CI status are both in the fingerprint, so the settled state
    (which may be failing) registers as its own change on a later tick.
    """
    return pr.changes_requested or pr.ci_status == "failing"


def compute_pr_fingerprint(pr: dict[str, Any]) -> str:
    """Fingerprint the actionable state of a PR for the CI follow-up loop.

    Keyed on the signals that mean the agent has real work to do — PR state, the
    CI check rollup, and whether changes are requested — never on ``updated_at``.
    GitHub bumps ``updated_at`` on any PR activity (comments, labels, reviews, the
    bot's own pushes), so hashing it re-poked the agent for every one of those long
    after the PR was opened.

    For the review signal we key on the boolean ``review_decision == "changes_requested"``
    rather than the raw decision: ``changes_requested`` is the only value that means
    the agent has code to fix, so an ``approved`` or ``review_required`` transition no
    longer re-pokes it for nothing.

    The head SHA is included so that a new commit failing with the same coarse
    ``ci_status`` as its predecessor still reads as a change — without it, an
    agent push that fails again would hash identically to the previous failure
    and the follow-up would never re-fire. The fingerprint only detects change;
    whether a change is worth firing on is decided by ``is_pr_actionable``.
    """
    changes_requested = pr.get("review_decision") == "changes_requested"
    fingerprint_source = "|".join(
        [str(pr.get(key, "")) for key in ("url", "state", "ci_status", "head_sha")] + [str(changes_requested)]
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
            # Snapshot (GraphQL) over the plain REST fetch: it carries the CI rollup
            # and review decision the fingerprint keys on, so the follow-up loop can
            # tell a real CI change or a changes-requested review from noise like
            # comments, approvals, or thread churn.
            pull_request = github_integration.get_pull_request_snapshot(pr_url)  # Validate PR URL and permissions
            if not pull_request.get("success"):
                return None
            fingerprint = compute_pr_fingerprint(pull_request)
        except Exception as e:
            # A failed snapshot fetch is almost always a transient GitHub hiccup (a network
            # blip, a rate limit, or a 200-with-`errors` GraphQL server error). Raise it as
            # transient so the activity's retry policy retries it, rather than a fatal
            # non-retryable error that permanently kills the in-flight follow-up run.
            raise ProcessTaskTransientError(
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
            ci_status=pull_request.get("ci_status", "none"),
            changes_requested=pull_request.get("review_decision") == "changes_requested",
        )
