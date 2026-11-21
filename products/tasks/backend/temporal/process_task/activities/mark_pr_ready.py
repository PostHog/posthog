from collections.abc import Collection
from typing import Any, Protocol

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.babysit_pr.snapshot import PRSnapshot
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.activities.get_pr_babysit_snapshot import load_gitlab_merge_request
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    get_github_integration,
    get_user_github_integration,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

KEEP_DRAFT_LABELS = frozenset({"keep-draft", "no-ci"})


@frozen
class MarkPrReadyInput:
    context: TaskProcessingContext
    snapshot: PRSnapshot


class _ReviewTarget(Protocol):
    def get_babysit_snapshot(self) -> dict[str, Any]: ...

    def mark_ready(self, *, skip_labels: Collection[str], expected_head_sha: str | None) -> dict[str, Any]: ...


@frozen
class _GitHubPullRequest:
    github: GitHubIntegration | UserGitHubIntegration
    pr_url: str
    repository: str
    number: int

    def get_babysit_snapshot(self) -> dict[str, Any]:
        return self.github.get_pull_request_babysit_snapshot(self.pr_url)

    def mark_ready(self, *, skip_labels: Collection[str], expected_head_sha: str | None) -> dict[str, Any]:
        return self.github.mark_pull_request_ready_for_review(
            self.repository, self.number, skip_labels=skip_labels, expected_head_sha=expected_head_sha
        )


def _run_still_wants_review(run: TaskRun, pr_url: str) -> bool:
    return (
        run.status == TaskRun.Status.IN_PROGRESS
        and (run.output or {}).get("pr_url") == pr_url
        and (run.state or {}).get("keep_draft") is not True
        and not run.has_pending_followup_messages
    )


def _review_target(context: TaskProcessingContext, pr_url: str) -> _ReviewTarget | None:
    if context.has_gitlab_credentials:
        return load_gitlab_merge_request(context, pr_url, "mark_pr_ready")
    if not context.has_github_credentials:
        return None
    parsed = GitHubIntegration.parse_pull_request_url(pr_url)
    if parsed is None or parsed.repository.casefold() != (context.repository or "").casefold():
        return None
    github = (
        get_github_integration(context.team_id, context.github_integration_id)
        if context.github_integration_id
        else get_user_github_integration(str(context.github_user_integration_id))
    )
    return _GitHubPullRequest(github=github, pr_url=pr_url, repository=parsed.repository, number=parsed.number)


@activity.defn
@close_db_connections
def mark_pr_ready(input: MarkPrReadyInput) -> bool:
    context = input.context
    with log_activity_execution("mark_pr_ready", **context.to_log_context()):
        try:
            if not (context.has_github_credentials or context.has_gitlab_credentials):
                return False
            if not input.snapshot.can_mark_ready:
                return False

            run = TaskRun.objects.filter(id=context.run_id, team_id=context.team_id).first()
            if run is None or not _run_still_wants_review(run, input.snapshot.pr_url):
                return False

            target = _review_target(context, input.snapshot.pr_url)
            if target is None:
                return False
            raw = target.get_babysit_snapshot()
            current = PRSnapshot.from_raw(raw, input.snapshot.pr_url)
            expected_branch = run.branch or context.branch or input.snapshot.head_ref
            if (
                not raw.get("success")
                or not expected_branch
                or current.head_ref != expected_branch
                or current != input.snapshot
                or not current.can_mark_ready
            ):
                activity.logger.info(
                    "task_pr_auto_ready_skipped", extra={"reason": "pr_changed", "run_id": context.run_id}
                )
                return False

            # The workflow checked its follow-up queue before it started this activity, and a
            # message the user sent since then only reached the run row. Read that row again here,
            # next to the mutation, so new work queued while the GitHub calls above were in flight
            # keeps the pull request in draft.
            fresh = TaskRun.objects.filter(id=context.run_id, team_id=context.team_id).first()
            if fresh is None or not _run_still_wants_review(fresh, input.snapshot.pr_url):
                activity.logger.info(
                    "task_pr_auto_ready_skipped", extra={"reason": "run_changed", "run_id": context.run_id}
                )
                return False

            result = target.mark_ready(skip_labels=KEEP_DRAFT_LABELS, expected_head_sha=current.head_sha)
            if result.get("success") is not True:
                activity.logger.warning("task_pr_auto_ready_rejected", extra={"run_id": context.run_id})
                return False
            changed = result.get("changed") is True
            activity.logger.info(
                "task_pr_auto_ready_evaluated",
                extra={"run_id": context.run_id, "changed": changed, "reason": result.get("reason")},
            )
            if changed and context.has_gitlab_credentials:
                # No webhook reports the change for GitLab, so record it now rather than on the next poll.
                try:
                    TaskRun.update_output_atomic(context.run_id, updates={"pr_state": "open"})
                except Exception:
                    activity.logger.warning("task_pr_auto_ready_persist_failed", exc_info=True)
            return changed
        except Exception:
            activity.logger.exception("task_pr_auto_ready_failed", extra={"run_id": context.run_id})
            return False
