from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.models import Integration
from posthog.models.github_integration_base import GitHubPullRequestComment
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.activities import TaskProcessingContext


@dataclass
class GetPrContextInput:
    context: TaskProcessingContext


@dataclass
class TrustedPrComment:
    """Serialization-safe representation of a trusted PR comment for Temporal payloads."""

    kind: str
    author: str | None
    author_association: str | None
    body: str
    html_url: str | None
    path: str | None = None
    line: int | None = None
    state: str | None = None


@dataclass
class GetPrContextOutput:
    pr_url: str
    pr_state: str
    fingerprint: str
    pr_author: str | None = None
    # Pre-filtered comments (trusted actors only). Defaulted so older workflow
    # histories that scheduled this activity before the comment fetch existed
    # still deserialize cleanly.
    trusted_review_comments: list[TrustedPrComment] = field(default_factory=list)
    trusted_reviews: list[TrustedPrComment] = field(default_factory=list)
    trusted_issue_comments: list[TrustedPrComment] = field(default_factory=list)


def _to_trusted_comment(comment: GitHubPullRequestComment) -> TrustedPrComment:
    return TrustedPrComment(
        kind=comment.kind,
        author=comment.author,
        author_association=comment.author_association,
        body=comment.body,
        html_url=comment.html_url,
        path=comment.path,
        line=comment.line,
        state=comment.state,
    )


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
            pull_request = github_integration.get_pull_request_from_url(pr_url)  # Validate PR URL and permissions
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

        pr_author_raw = pull_request.get("author")
        pr_author = pr_author_raw if isinstance(pr_author_raw, str) else None
        repository = pull_request.get("repository")
        pr_number = pull_request.get("number")

        trusted_review_comments: list[TrustedPrComment] = []
        trusted_reviews: list[TrustedPrComment] = []
        trusted_issue_comments: list[TrustedPrComment] = []
        # Fetch pre-filtered comments so the workflow can embed them in the CI
        # follow-up prompt without ever exposing untrusted prose to the LLM.
        # A failure to fetch is non-fatal: we still return the PR context so
        # the change-detection fingerprint stays correct, and the prompt
        # builder treats the empty list as "no trusted feedback yet".
        if isinstance(repository, str) and isinstance(pr_number, int):
            try:
                feedback = github_integration.get_pull_request_feedback(
                    repository,
                    pr_number,
                    trusted_only=True,
                    pr_author=pr_author,
                )
                trusted_review_comments = [_to_trusted_comment(c) for c in feedback.get("review_comments", [])]
                trusted_reviews = [_to_trusted_comment(c) for c in feedback.get("reviews", [])]
                trusted_issue_comments = [_to_trusted_comment(c) for c in feedback.get("issue_comments", [])]
            except Exception:
                activity.logger.warning(
                    "get_pr_context_feedback_fetch_failed",
                    pr_url=pr_url,
                    exc_info=True,
                )

        return GetPrContextOutput(
            pr_url=pr_url,
            pr_state=pull_request.get("state", "unknown"),
            fingerprint=fingerprint,
            pr_author=pr_author,
            trusted_review_comments=trusted_review_comments,
            trusted_reviews=trusted_reviews,
            trusted_issue_comments=trusted_issue_comments,
        )
