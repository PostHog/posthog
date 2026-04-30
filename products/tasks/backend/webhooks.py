import hmac
import uuid
import asyncio
import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
import posthoganalytics
from pydantic import ValidationError

from posthog.models.instance_setting import get_instance_setting
from posthog.temporal.common.client import sync_connect

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow
from products.tasks.backend.webhook_schemas import CheckRunEvent, CommentEvent, PullRequestEvent

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

TASK_RUN_SELECT_RELATED = ("task", "task__created_by", "team")

MAX_COMMENT_BODY_LENGTH = 4000

RESUME_COOLDOWN = timedelta(seconds=60)

CHECK_RUN_ACCEPTABLE_CONCLUSIONS = {"success", "neutral", "cancelled", "skipped"}


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


@csrf_exempt
def github_pr_webhook(request: HttpRequest) -> HttpResponse:
    """
    Handle GitHub webhook events for pull requests and PR comments.

    This endpoint:
    1. Validates the HMAC-SHA256 signature from GitHub
    2. Dispatches to event-specific handlers based on X-GitHub-Event header

    Supported events:
    - pull_request: PR lifecycle (opened, closed, merged)
    - issue_comment: General PR comments
    - pull_request_review_comment: Inline code review comments
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    webhook_secret = get_github_webhook_secret()
    if not webhook_secret:
        logger.error(
            "github_pr_webhook_no_secret",
            message="GITHUB_WEBHOOK_SECRET not configured",
        )
        return HttpResponse("Webhook not configured", status=500)

    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature(request.body, signature, webhook_secret):
        logger.warning(
            "github_pr_webhook_invalid_signature",
            has_signature=bool(signature),
        )
        return HttpResponse("Invalid signature", status=403)

    event_type = request.headers.get("X-GitHub-Event")
    raw = request.body

    try:
        if event_type == "pull_request":
            return _handle_pull_request_event(PullRequestEvent.model_validate_json(raw))
        elif event_type in ("issue_comment", "pull_request_review_comment", "pull_request_review"):
            return _handle_comment_event(CommentEvent.model_validate_json(raw))
        elif event_type == "check_run":
            return _handle_check_run_event(CheckRunEvent.model_validate_json(raw))
        else:
            return HttpResponse(status=200)
    except ValidationError as e:
        logger.warning(
            "github_pr_webhook_invalid_payload",
            event_type=event_type,
            errors=e.errors(),
        )
        return HttpResponse("Invalid payload", status=400)


def _handle_check_run_event(event: CheckRunEvent) -> HttpResponse:
    check_run = event.check_run
    logger.info(
        "github_check_run_webhook_received",
        action=event.action,
        check_run_name=check_run.name,
        repository=event.repository.full_name,
    )
    if event.action != "completed":
        return HttpResponse(status=200)

    pr_url = check_run.pull_requests[0].url if check_run.pull_requests else None
    conclusion = check_run.conclusion
    if conclusion not in CHECK_RUN_ACCEPTABLE_CONCLUSIONS:
        logger.info(
            "github_check_run_unacceptable_conclusion",
            conclusion=conclusion,
            check_run_name=check_run.name,
        )
        if pr_url:
            task_run = find_task_run(pr_url=pr_url, branch=None)
            if task_run:
                task_run.emit_console_event(
                    "info", f"Check run '{check_run.name}' completed with conclusion: {conclusion}"
                )
                task_run.capture_event(
                    "check_run_completed", {"check_run_name": check_run.name, "conclusion": conclusion}
                )
                _forward_pr_activity_to_task(pr_url=pr_url, branch=None)

    return HttpResponse(status=200)


def _handle_pull_request_event(event: PullRequestEvent) -> HttpResponse:
    action = event.action
    pull_request = event.pull_request
    pr_url = pull_request.html_url
    merged = pull_request.merged

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

    branch = pull_request.head.ref
    repository_full_name = event.repository.full_name
    task_run = find_task_run(pr_url=pr_url, branch=branch, repository=repository_full_name)

    if not task_run:
        logger.debug(
            "github_pr_webhook_no_task_run",
            action=action,
            pr_url=pr_url,
            message="No TaskRun found with this PR URL",
        )
        return HttpResponse(status=200)

    task_run.emit_console_event("info", f"PR {event_action}: {pr_url}")

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

    return HttpResponse(status=200)


def _handle_comment_event(event: CommentEvent) -> HttpResponse:
    if event.action != "created":
        return HttpResponse(status=200)

    # issue_comment fires for issues too — only PR comments have issue.pull_request
    pull_request = event.pull_request or (event.issue.pull_request if event.issue else None)
    if not pull_request:
        return HttpResponse(status=200)

    pr_url = pull_request.html_url
    if not pr_url:
        return HttpResponse(status=200)

    branch = pull_request.head.ref
    _forward_pr_activity_to_task(pr_url=pr_url, branch=branch)
    return HttpResponse(status=200)


def _forward_pr_activity_to_task(
    pr_url: str,
    branch: str | None,
) -> None:
    task_run = find_task_run(pr_url=pr_url, branch=branch)
    if not task_run:
        logger.debug("github_comment_webhook_no_task_run", pr_url=pr_url)
        return
    user: User = task_run.task.created_by
    if not user:
        logger.warning(
            "github_comment_webhook_no_user",
            pr_url=pr_url,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
        )
        return
    org_id = user.current_organization_id
    if not posthoganalytics.feature_enabled(
        "github-comment-auto-resume",
        user.distinct_id,
        groups={"organization": org_id},
        group_properties={"organization": {"id": org_id}},
    ):
        logger.debug(
            "github_comment_auto_resume_disabled",
            pr_url=pr_url,
            user_id=user.pk,
        )
        return
    task_run.emit_console_event("info", f"New comment on PR: {pr_url}")
    task_run.capture_event("pr_comment_received", {"pr_url": pr_url})

    if not task_run.is_terminal:
        _signal_running_workflow(task_run)
    else:
        _create_resume_run(task_run, pr_url)


def _signal_running_workflow(task_run: TaskRun) -> None:
    try:
        client = sync_connect()
        handle = client.get_workflow_handle(task_run.workflow_id)

        asyncio.run(handle.signal(ProcessTaskWorkflow.pr_event))

        logger.info(
            "github_comment_signaled_workflow",
            run_id=str(task_run.id),
            workflow_id=task_run.workflow_id,
        )
    except Exception as e:
        logger.warning(
            "github_comment_signal_failed",
            run_id=str(task_run.id),
            error=str(e),
        )


def _create_resume_run(task_run: TaskRun, pr_url: str) -> None:
    from products.tasks.backend.temporal.client import execute_task_processing_workflow

    task = task_run.task
    created_by = task.created_by

    if not created_by:
        logger.warning(
            "github_comment_no_created_by",
            task_id=str(task.id),
            run_id=str(task_run.id),
        )
        return

    snapshot_ext_id = (task_run.state or {}).get("snapshot_external_id")

    if pr_url:
        contextualized_message = (
            f"[CONTEXT: This task already has an open pull request: {pr_url}\n"
            f"Check out the existing PR branch with `gh pr checkout {pr_url}`, "
            "make your changes, commit, and push to that branch. "
            "Do NOT create a new branch or PR. Inspect the PR and address any new findings]\n\n"
        )
    else:
        contextualized_message = ""

    extra_state: dict = {
        "resume_from_run_id": str(task_run.id),
        "pending_user_message": contextualized_message,
    }
    if snapshot_ext_id:
        extra_state["snapshot_external_id"] = snapshot_ext_id

    new_run = task.create_run(mode="background", extra_state=extra_state)

    execute_task_processing_workflow(
        task_id=str(task.id),
        run_id=str(new_run.id),
        team_id=task.team_id,
        user_id=created_by.id,
        skip_user_check=True,
    )

    logger.info(
        "github_comment_created_resume_run",
        task_id=str(task.id),
        old_run_id=str(task_run.id),
        new_run_id=str(new_run.id),
    )
