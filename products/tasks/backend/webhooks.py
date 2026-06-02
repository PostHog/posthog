import hmac
import uuid
import hashlib

from django.http import HttpResponse

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import Integration
from posthog.models.team.team import Team

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

    logger.info(
        "github_pr_webhook_processed",
        action=action,
        event_action=event_action,
        pr_url=pr_url,
        pr_source="task" if task_run else "external",
        task_id=str(task_run.task_id) if task_run else None,
        run_id=str(task_run.id) if task_run else None,
    )

    # Deterministic UUID dedupes duplicate webhook deliveries of the same PR action.
    event_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pr_url}:{analytics_event}"))
    _capture_pr_event(payload, task_run, analytics_event, event_uuid)

    if task_run and action == "closed" and merged:
        _resolve_signal_reports_for_task(task_run.task_id, pr_url)

    return HttpResponse(status=200)


# Nulled on external PRs so their schema matches task-originated PR events.
_TASK_ATTRIBUTION_KEYS = ("task_id", "run_id", "origin_product", "signal_report_id", "environment", "mode", "title")


def _pr_payload_properties(payload: dict) -> dict:
    pull_request = payload.get("pull_request") or {}
    return {
        "pr_url": pull_request.get("html_url"),
        "pr_number": pull_request.get("number"),
        "pr_author": (pull_request.get("user") or {}).get("login"),
        "pr_base_ref": (pull_request.get("base") or {}).get("ref"),
        "pr_head_ref": (pull_request.get("head") or {}).get("ref"),
    }


def _capture_pr_event(payload: dict, task_run: TaskRun | None, analytics_event: str, event_uuid: str) -> None:
    pr_properties = _pr_payload_properties(payload)

    if task_run is not None:
        task_run.capture_event(analytics_event, {**pr_properties, "pr_source": "task"}, event_uuid=event_uuid)
        return

    team = _resolve_external_team(payload)
    if team is None:
        logger.debug("github_pr_webhook_unresolved_installation", pr_url=pr_properties.get("pr_url"))
        return

    properties: dict = {
        **pr_properties,
        "repository": ((payload.get("repository") or {}).get("full_name") or "").strip().lower() or None,
        "pr_source": "external",
        "team_id": team.id,
        # title omitted to avoid leaking customer business context.
        **dict.fromkeys(_TASK_ATTRIBUTION_KEYS, None),
    }

    try:
        posthoganalytics.capture(
            distinct_id=str(team.uuid),
            event=analytics_event,
            properties=properties,
            groups=groups(team=team),
            uuid=event_uuid,
        )
    except Exception as e:
        logger.warning("github_pr_webhook_capture_failed", analytics_event=analytics_event, error=str(e))


def _resolve_external_team(payload: dict) -> Team | None:
    installation_id = (payload.get("installation") or {}).get("id")
    if installation_id is None:
        return None

    # One installation can map to multiple teams; order_by makes attribution deterministic.
    integration = (
        Integration.objects.filter(kind="github", integration_id=str(installation_id))
        .select_related("team")
        .order_by("team_id")
        .first()
    )
    return integration.team if integration else None


def _resolve_signal_reports_for_task(task_id: uuid.UUID, pr_url: str) -> None:
    """Mark signal reports linked to a merged PR's task as resolved.

    Kept tolerant: a single bad transition should not fail the whole webhook,
    since GitHub retries 5xx responses and we've already acknowledged the PR event.
    """
    reports = (
        SignalReport.objects.filter(report_tasks__task_id=task_id)
        .exclude(
            status__in=[
                SignalReport.Status.RESOLVED,
                SignalReport.Status.DELETED,
                SignalReport.Status.SUPPRESSED,
            ]
        )
        .distinct()
    )

    for report in reports:
        try:
            updated_fields = report.transition_to(SignalReport.Status.RESOLVED)
        except InvalidStatusTransition:
            logger.warning(
                "github_pr_webhook_signal_report_invalid_transition",
                report_id=str(report.id),
                from_status=report.status,
                pr_url=pr_url,
            )
            continue
        report.save(update_fields=updated_fields)
        logger.info(
            "github_pr_webhook_signal_report_resolved",
            report_id=str(report.id),
            task_id=str(task_id),
            pr_url=pr_url,
        )
