import hmac
import json
import asyncio
import uuid
import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import structlog
import posthoganalytics

from posthog.models.instance_setting import get_instance_setting
from posthog.temporal.common.client import sync_connect

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

TASK_RUN_SELECT_RELATED = ("task", "task__created_by", "team")

MAX_COMMENT_BODY_LENGTH = 4000

RESUME_COOLDOWN = timedelta(seconds=60)


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

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    event_type = request.headers.get("X-GitHub-Event")

    if event_type == "pull_request":
        return _handle_pull_request_event(payload)
    elif event_type == "issue_comment":
        return _handle_issue_comment_event(payload)
    elif event_type == "pull_request_review_comment":
        return _handle_review_comment_event(payload)
    else:
        return HttpResponse(status=200)


def _handle_pull_request_event(payload: dict) -> HttpResponse:
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


def _handle_issue_comment_event(payload: dict) -> HttpResponse:
    action = payload.get("action")
    if action != "created":
        return HttpResponse(status=200)

    comment = payload.get("comment", {})
    issue = payload.get("issue", {})

    # Only process comments on PRs (issue_comment fires for issues too)
    if "pull_request" not in issue:
        return HttpResponse(status=200)

    commenter = comment.get("user", {})
    if commenter.get("type") == "Bot":
        return HttpResponse(status=200)

    pr_url = issue.get("pull_request", {}).get("html_url")
    if not pr_url:
        return HttpResponse(status=200)

    comment_body = comment.get("body", "")[:MAX_COMMENT_BODY_LENGTH]
    commenter_login = commenter.get("login", "unknown")

    message = f"[GitHub PR Comment from @{commenter_login}]\n{comment_body}"

    _forward_comment_to_task(pr_url=pr_url, branch=None, message=message)
    return HttpResponse(status=200)


def _handle_review_comment_event(payload: dict) -> HttpResponse:
    action = payload.get("action")
    if action != "created":
        return HttpResponse(status=200)

    comment = payload.get("comment", {})
    pull_request = payload.get("pull_request", {})

    commenter = comment.get("user", {})
    if commenter.get("type") == "Bot":
        return HttpResponse(status=200)

    pr_url = pull_request.get("html_url")
    if not pr_url:
        return HttpResponse(status=200)

    comment_body = comment.get("body", "")[:MAX_COMMENT_BODY_LENGTH]
    commenter_login = commenter.get("login", "unknown")
    file_path = comment.get("path", "")
    line = comment.get("original_line") or comment.get("line")
    diff_hunk = comment.get("diff_hunk", "")

    location = f" on `{file_path}`" if file_path else ""
    location += f" (line {line})" if line else ""

    message = f"[GitHub Review Comment from @{commenter_login}{location}]\n"
    if diff_hunk:
        message += f"```diff\n{diff_hunk}\n```\n"
    message += comment_body

    branch = pull_request.get("head", {}).get("ref")
    _forward_comment_to_task(pr_url=pr_url, branch=branch, message=message)
    return HttpResponse(status=200)


def _forward_comment_to_task(
    pr_url: str | None,
    branch: str | None,
    message: str,
) -> None:
    task_run = find_task_run(pr_url=pr_url, branch=branch)
    if not task_run:
        logger.debug("github_comment_webhook_no_task_run", pr_url=pr_url)
        return
    user: User = task_run.task.created_by
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
        _signal_running_workflow(task_run, message)
    else:
        _create_resume_run(task_run, message, pr_url)


def _signal_running_workflow(task_run: TaskRun, message: str) -> None:
    try:
        client = sync_connect()
        handle = client.get_workflow_handle(task_run.workflow_id)

        asyncio.run(handle.signal(ProcessTaskWorkflow.send_followup_message, message))

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


def _create_resume_run(task_run: TaskRun, message: str, pr_url: str | None) -> None:
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

    # Rate limit: if a non-terminal run was created recently for this task, signal it instead
    recent_run = (
        TaskRun.objects.filter(task=task, created_at__gt=timezone.now() - RESUME_COOLDOWN)
        .order_by("-created_at")
        .select_related(*TASK_RUN_SELECT_RELATED)
        .first()
    )
    if recent_run and not recent_run.is_terminal:
        logger.info("github_comment_signaling_recent_run", task_id=str(task.id), run_id=str(recent_run.id))
        _signal_running_workflow(recent_run, message)
        return

    snapshot_ext_id = (task_run.state or {}).get("snapshot_external_id")

    if pr_url:
        contextualized_message = (
            f"[CONTEXT: This task already has an open pull request: {pr_url}\n"
            f"Check out the existing PR branch with `gh pr checkout {pr_url}`, "
            "make your changes, commit, and push to that branch. "
            "Do NOT create a new branch or PR.]\n\n" + message
        )
    else:
        contextualized_message = message

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
