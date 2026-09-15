import posthoganalytics
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.babysit_pr.snapshot import PRSnapshot
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.activities.get_pr_context import (
    get_github_integration,
    get_user_github_integration,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

AUTO_READY_FEATURE_FLAG = "tasks-pr-auto-ready"
KEEP_DRAFT_LABELS = frozenset({"keep-draft", "no-ci"})


@frozen
class MarkPrReadyInput:
    context: TaskProcessingContext
    snapshot: PRSnapshot


@activity.defn
@close_db_connections
def mark_pr_ready(input: MarkPrReadyInput) -> bool:
    context = input.context
    with log_activity_execution("mark_pr_ready", **context.to_log_context()):
        try:
            if not context.has_github_credentials or not input.snapshot.can_mark_ready:
                return False
            enabled = posthoganalytics.feature_enabled(
                AUTO_READY_FEATURE_FLAG,
                distinct_id=context.distinct_id,
                groups={"organization": context.organization_id},
                group_properties={"organization": {"id": context.organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
            if enabled is not True:
                return False

            run = TaskRun.objects.filter(id=context.run_id, team_id=context.team_id).first()
            if (
                run is None
                or run.status != TaskRun.Status.IN_PROGRESS
                or (run.output or {}).get("pr_url") != input.snapshot.pr_url
                or (run.state or {}).get("keep_draft") is True
            ):
                return False

            parsed = GitHubIntegration.parse_pull_request_url(input.snapshot.pr_url)
            if parsed is None or f"{parsed.owner}/{parsed.repo}".casefold() != (context.repository or "").casefold():
                return False
            github = (
                get_github_integration(context.github_integration_id)
                if context.github_integration_id
                else get_user_github_integration(str(context.github_user_integration_id))
            )
            raw = github.get_pull_request_babysit_snapshot(input.snapshot.pr_url)
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

            result = github.mark_pull_request_ready_for_review(
                f"{parsed.owner}/{parsed.repo}",
                parsed.number,
                skip_labels=KEEP_DRAFT_LABELS,
                expected_head_sha=current.head_sha,
            )
            if result.get("success") is not True:
                activity.logger.warning("task_pr_auto_ready_rejected", extra={"run_id": context.run_id})
                return False
            changed = result.get("success") is True and result.get("changed") is True
            activity.logger.info(
                "task_pr_auto_ready_evaluated",
                extra={"run_id": context.run_id, "changed": changed, "reason": result.get("reason")},
            )
            return changed
        except Exception:
            activity.logger.exception("task_pr_auto_ready_failed", extra={"run_id": context.run_id})
            return False
