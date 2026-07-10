import hmac
import uuid
import hashlib

from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import HttpResponse

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.signals.backend.models import InvalidStatusTransition, SignalReport
from products.tasks.backend.facade.api import signal_workflow_completion
from products.tasks.backend.models import TaskRun
from products.tasks.backend.prompts import WIZARD_HEAD_BRANCH_PREFIX

logger = structlog.get_logger(__name__)

TASK_RUN_SELECT_RELATED = ("task", "task__created_by", "team")

_TERMINAL_RUN_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


def find_task_run(
    pr_url: str | None = None,
    branch: str | None = None,
    repository: str | None = None,
) -> TaskRun | None:
    repository = repository.strip() if repository else None

    if pr_url:
        # A resumed wizard run inherits its predecessor's head branch, so a terminal
        # original and its live resume can both claim the same PR URL. Scope to the
        # webhook's repo and prefer non-terminal runs so merge handling lands on the
        # run that can still act on it.
        runs = TaskRun.objects.filter(output__pr_url=pr_url)
        if repository:
            runs = runs.filter(task__repository__iexact=repository)
        task_run = (
            runs.annotate(
                terminal_rank=Case(
                    When(status__in=_TERMINAL_RUN_STATUSES, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            .order_by("terminal_rank", "-created_at")
            .select_related(*TASK_RUN_SELECT_RELATED)
            .first()
        )
        if task_run:
            return task_run

    # Branch-only lookups must be scoped to the repository the webhook came from.
    # Without this, a PR opened on an unrelated repo with a colliding branch name
    # (e.g. "main") gets attributed to whichever TaskRun shares that branch.
    if branch and repository:
        # Wizard runs are excluded here: their `branch` column holds the checkout (base)
        # branch, so a same-repo PR whose head ref equals the base (e.g. "main") would
        # otherwise claim the run before the dedicated leg below is consulted.
        task_run = (
            TaskRun.objects.filter(
                branch=branch,
                task__repository__iexact=repository,
                state__wizard_head_branch__isnull=True,
            )
            .select_related(*TASK_RUN_SELECT_RELATED)
            .first()
        )
        if task_run:
            return task_run

        # Wizard cloud runs push to a server-generated head branch stored in run state.
        # The prefix check keeps this leg off the hot path for ordinary PR webhooks, and
        # terminal runs are excluded so a reopened branch can't fire events on a dead run
        # (post-merge events for bound runs resolve via the pr_url leg above).
        if branch.startswith(WIZARD_HEAD_BRANCH_PREFIX):
            task_run = (
                TaskRun.objects.filter(
                    state__wizard_head_branch=branch,
                    task__repository__iexact=repository,
                    task__deleted=False,
                )
                .exclude(status__in=_TERMINAL_RUN_STATUSES)
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

    # Backstop the agent-side PR detector: when we matched the run (by branch+repo)
    # but its output carries no PR URL yet, persist it so the inbox-notification
    # gate, CI follow-up loop, and later webhook lookups can resolve the PR.
    # Only trust the match when the PR originates from a branch in the installed
    # repo itself — never a fork. For fork PRs, head.ref is attacker-controlled
    # while repository.full_name stays the base repo, so a branch+repo match could
    # otherwise bind an unrelated PR to the run.
    head_repo_full_name = ((pull_request.get("head") or {}).get("repo") or {}).get("full_name")
    is_internal_branch = (
        head_repo_full_name is not None
        and repository_full_name is not None
        and head_repo_full_name.strip().lower() == repository_full_name.strip().lower()
    )
    if task_run is not None and is_internal_branch:
        _record_run_pr_url(task_run, pr_url)

    # Deterministic UUID dedupes duplicate webhook deliveries of the same PR action.
    event_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pr_url}:{analytics_event}"))
    _capture_pr_event(payload, task_run, analytics_event, event_uuid)

    if task_run and action == "closed" and merged:
        # Only trust the merge for the run that actually claims this PR URL. The pr_url backstop
        # above already covers branch-matched internal PRs, so requiring equality here keeps a
        # same-branch webhook for a different PR from marking this run's PR as merged.
        run_output = task_run.output if isinstance(task_run.output, dict) else {}
        if run_output.get("pr_url") == pr_url:
            _record_run_pr_merged(task_run)
        _resolve_signal_reports_for_task(task_run.task_id, pr_url)

    return HttpResponse(status=200)


def _record_run_pr_url(task_run: TaskRun, pr_url: str) -> None:
    """Persist ``output.pr_url`` for a webhook-matched run when it isn't set yet.

    The agent server normally records the PR URL when it observes the agent open
    the PR. When that detection misses, a branch+repo webhook match is the
    backstop — without this the run is recognized for analytics but its
    ``output.pr_url`` stays empty, so inbox notifications, the CI follow-up loop,
    and later webhook lookups never resolve the PR.
    """
    if not _record_run_output_field(task_run, "pr_url", pr_url, "github_pr_webhook_record_pr_url_failed"):
        return
    # Publish-only (no append_log): the S3 run log has a live writer — the agent is streaming
    # log batches at exactly this moment — and append_log's read-modify-write would race it.
    # Tolerant: a stream hiccup must not fail the webhook; clients recover on refetch.
    try:
        for event in (
            task_run.build_progress_event("pr", "completed", "Opened pull request", "setup", detail=pr_url),
            task_run.build_progress_event("ci", "in_progress", "Keeping CI green", "setup"),
        ):
            task_run.publish_stream_event(event)
        task_run.publish_stream_state_event()
    except Exception:
        logger.warning("github_pr_webhook_pr_events_failed", run_id=str(task_run.id), exc_info=True)


def _record_run_pr_merged(task_run: TaskRun) -> None:
    """Persist ``output.pr_merged`` when the run's PR is merged.

    Surfaces that gate on merge state (e.g. the pre-ingestion sample-data placeholder pointing at
    the wizard's setup PR) read it off the run's ``output``, which is the only PR state the task
    APIs expose.
    """
    if not _record_run_output_field(task_run, "pr_merged", True, "github_pr_webhook_record_pr_merged_failed"):
        return
    # Publish-only (no append_log), same rationale and failure tolerance as _record_run_pr_url.
    try:
        pr_url = task_run.output.get("pr_url") if isinstance(task_run.output, dict) else None
        task_run.publish_stream_event(
            task_run.build_progress_event("pr", "completed", "Pull request merged", "setup", detail=pr_url)
        )
        task_run.publish_stream_state_event()
    except Exception:
        logger.warning("github_pr_webhook_pr_merged_events_failed", run_id=str(task_run.id), exc_info=True)
    _complete_wizard_run_on_merge(task_run)


def _complete_wizard_run_on_merge(task_run: TaskRun) -> None:
    """Wind down a wizard cloud run's Temporal workflow once its PR merges.

    A wizard run's only deliverable is its setup PR; once that merges, nothing is left for the
    sandbox to do, yet without this signal the workflow idles until the sandbox TTL expires and
    the onboarding UI reports the run as running for hours. Best-effort: the webhook must stay
    2xx even if Temporal is unreachable or the workflow already finished.
    """
    state = task_run.state if isinstance(task_run.state, dict) else {}
    if "wizard_config" not in state:
        return
    if task_run.environment != TaskRun.Environment.CLOUD:
        return
    if task_run.status in _TERMINAL_RUN_STATUSES:
        return

    def _signal() -> None:
        try:
            signal_workflow_completion(task_run.id, TaskRun.Status.COMPLETED, None)
        except Exception:
            logger.warning("github_pr_webhook_wizard_completion_signal_failed", run_id=str(task_run.id), exc_info=True)

    # The pr_merged write has committed by the time the caller's atomic block exits; on_commit
    # keeps the signal after that commit even if this path ever runs inside an outer transaction.
    transaction.on_commit(_signal)


def _record_run_output_field(task_run: TaskRun, key: str, value: str | bool, failure_log_event: str) -> bool:
    """Idempotently merge ``{key: value}`` into a run's ``output`` JSON under a row lock.

    Returns True only when this call performed the write, so callers can fire follow-on
    side effects exactly once. Tolerant: a failure here must not fail the webhook (GitHub
    retries 5xx, and the event is already handled).
    """
    if isinstance(task_run.output, dict) and task_run.output.get(key):
        return False
    try:
        with transaction.atomic():
            locked = TaskRun.objects.select_for_update().get(id=task_run.id)
            output = locked.output if isinstance(locked.output, dict) else {}
            if output.get(key):
                return False
            locked.output = {**output, key: value}
            locked.save(update_fields=["output", "updated_at"])
        # Keep the in-memory instance consistent for the rest of this request.
        task_run.output = locked.output
        return True
    except Exception:
        logger.warning(failure_log_event, run_id=str(task_run.id), exc_info=True)
        return False


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
        "pr_additions": pull_request.get("additions"),
        "pr_deletions": pull_request.get("deletions"),
        "pr_changed_files": pull_request.get("changed_files"),
        "pr_commits": pull_request.get("commits"),
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
        SignalReport.objects.filter(SignalReport.reports_for_task_filter(task_id))
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
