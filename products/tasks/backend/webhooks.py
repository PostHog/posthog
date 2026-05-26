import hmac
import uuid
import hashlib

from django.http import HttpResponse

import structlog

from posthog.models.instance_setting import get_instance_setting

from products.signals.backend.models import InvalidStatusTransition, SignalReport
from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

TASK_RUN_SELECT_RELATED = ("task", "task__created_by", "team")


def find_task_run(
    pr_url: str | None = None,
    branch: str | None = None,
    repository: str | None = None,
) -> TaskRun | None:
    if pr_url:
        task_run = TaskRun.objects.filter(output__pr_url=pr_url).select_related(*TASK_RUN_SELECT_RELATED).first()
        if task_run:
            return task_run

    # Branch-only lookups must be scoped to the repository the webhook came from.
    # Without this, a PR opened on an unrelated repo with a colliding branch name
    # (e.g. "main") gets attributed to whichever TaskRun shares that branch.
    repository = repository.strip() if repository else None
    if branch and repository:
        task_run = (
            TaskRun.objects.filter(branch=branch, task__repository__iexact=repository)
            .select_related(*TASK_RUN_SELECT_RELATED)
            .first()
        )
        if task_run:
            return task_run

    return None


def verify_github_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    """
    Verify the GitHub webhook signature using HMAC-SHA256.

    GitHub sends a signature in the X-Hub-Signature-256 header in the format:
    sha256=<hex_digest>
    """
    if not signature or not signature.startswith("sha256="):
        return False

    expected_signature = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(expected_signature, signature)


def get_github_webhook_secret() -> str | None:
    """Get the GitHub webhook secret from instance settings."""
    secret = get_instance_setting("GITHUB_WEBHOOK_SECRET")
    return secret if secret else None


def handle_pull_request_event(payload: dict) -> HttpResponse:
    """Process a pre-verified pull_request webhook event.

    Called from ``posthog.urls.github_webhook`` (unified dispatcher).
    """
    action = payload.get("action")
    pull_request = payload.get("pull_request", {})
    pr_url = pull_request.get("html_url")
    merged = pull_request.get("merged", False)

    if not pr_url:
        logger.warning("github_pr_webhook_no_pr_url", action=action)
        return HttpResponse(status=200)

    if action == "opened":
        event_action = "created"
        analytics_event = "pr_created"
    elif action == "closed":
        if merged:
            event_action = "merged"
            analytics_event = "pr_merged"
        else:
            event_action = "closed"
            analytics_event = "pr_closed"
    else:
        logger.debug("github_pr_webhook_ignored_action", action=action, pr_url=pr_url)
        return HttpResponse(status=200)

    branch = pull_request.get("head", {}).get("ref")
    repository_full_name = (payload.get("repository") or {}).get("full_name")
    task_run = find_task_run(pr_url=pr_url, branch=branch, repository=repository_full_name)

    if not task_run:
        logger.debug(
            "github_pr_webhook_no_task_run",
            action=action,
            pr_url=pr_url,
            message="No TaskRun found with this PR URL",
        )
        return HttpResponse(status=200)

    logger.info(
        "github_pr_webhook_processed",
        action=action,
        event_action=event_action,
        pr_url=pr_url,
        task_id=str(task_run.task_id),
        run_id=str(task_run.id),
    )

    # Generate a deterministic UUID from the PR URL and event type so that
    # duplicate webhook deliveries for the same PR action are deduplicated.
    event_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pr_url}:{analytics_event}"))
    task_run.capture_event(analytics_event, {"pr_url": pr_url}, event_uuid=event_uuid)

    if action == "closed" and merged:
        _resolve_signal_reports_for_task(task_run.task_id, pr_url)

    return HttpResponse(status=200)


def _resolve_signal_reports_for_task(task_id: uuid.UUID, pr_url: str) -> None:
    """Mark signal reports linked to a merged PR's task as resolved.

    Kept tolerant: a single bad transition should not fail the whole webhook,
    since GitHub retries 5xx responses and we've already acknowledged the PR event.
    """
    terminal_statuses = (
        SignalReport.Status.RESOLVED,
        SignalReport.Status.DELETED,
        SignalReport.Status.SUPPRESSED,
    )
    linked_reports = list(
        SignalReport.objects.filter(report_tasks__task_id=task_id).distinct().only("id", "status")
    )
    reports_to_resolve = [r for r in linked_reports if r.status not in terminal_statuses]
    skipped_terminal = [r for r in linked_reports if r.status in terminal_statuses]

    # Always emit a summary so we can tell, from logs alone, whether the merge handler
    # ran, how many reports were linked, and why we did/didn't transition any of them.
    logger.info(
        "github_pr_webhook_signal_report_resolution_started",
        task_id=str(task_id),
        pr_url=pr_url,
        linked_report_count=len(linked_reports),
        candidate_report_count=len(reports_to_resolve),
        skipped_terminal_count=len(skipped_terminal),
        skipped_terminal_report_ids=[str(r.id) for r in skipped_terminal],
        candidate_report_ids=[str(r.id) for r in reports_to_resolve],
    )

    resolved_count = 0
    invalid_transition_count = 0
    for report in reports_to_resolve:
        try:
            updated_fields = report.transition_to(SignalReport.Status.RESOLVED)
        except InvalidStatusTransition:
            invalid_transition_count += 1
            logger.warning(
                "github_pr_webhook_signal_report_invalid_transition",
                report_id=str(report.id),
                from_status=report.status,
                task_id=str(task_id),
                pr_url=pr_url,
            )
            continue
        report.save(update_fields=updated_fields)
        resolved_count += 1
        logger.info(
            "github_pr_webhook_signal_report_resolved",
            report_id=str(report.id),
            task_id=str(task_id),
            pr_url=pr_url,
        )

    logger.info(
        "github_pr_webhook_signal_report_resolution_finished",
        task_id=str(task_id),
        pr_url=pr_url,
        resolved_count=resolved_count,
        invalid_transition_count=invalid_transition_count,
        skipped_terminal_count=len(skipped_terminal),
    )
