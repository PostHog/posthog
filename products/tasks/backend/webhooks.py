import hmac
import uuid
import asyncio
import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING

from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse

import structlog
import posthoganalytics
from pydantic import ValidationError

from posthog.models.instance_setting import get_instance_setting
from posthog.temporal.common.client import sync_connect

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow
from products.tasks.backend.webhook_schemas import CheckRunEvent, Comment, CommentEvent, PullRequestEvent

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

TASK_RUN_SELECT_RELATED = ("task", "task__created_by", "team")

MAX_COMMENT_BODY_LENGTH = 4000

# Cooldown between resume runs spawned from the same task. Prevents a flood of
# webhook deliveries (CI fan-out, multiple review comments, attacker comments)
# from spinning up parallel cloud sandboxes.
RESUME_COOLDOWN = timedelta(seconds=60)

# Hard cap on how many resume runs may be spawned from a single base run, even
# spread out over time. Belt-and-braces against the cooldown being defeated.
MAX_RESUMES = 10

CHECK_RUN_ACCEPTABLE_CONCLUSIONS = {"success", "neutral", "cancelled", "skipped"}

# Comment author types we never react to. GitHub uses "Bot" for app accounts and
# "Mannequin" for system mirroring; both indicate non-human authorship.
IGNORED_COMMENT_USER_TYPES = {"Bot", "Mannequin"}


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


def handle_github_webhook(event_type: str, payload: dict) -> HttpResponse:
    try:
        match event_type:
            case "issue_comment" | "pull_request_review_comment" | "pull_request_review":
                return _handle_comment_event(CommentEvent.model_validate(payload), event_type=event_type)
            case "check_run":
                return _handle_check_run_event(CheckRunEvent.model_validate(payload))
            case "pull_request":
                return _handle_pull_request_event(PullRequestEvent.model_validate(payload))
            case _:
                logger.debug("github_webhook_unhandled_event_type", event_type=event_type)
                return HttpResponse(status=200)
    except ValidationError as e:
        logger.warning("github_webhook_payload_validation_failed", event_type=event_type, error=str(e))
        return HttpResponse(status=400)

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
    if conclusion in CHECK_RUN_ACCEPTABLE_CONCLUSIONS:
        return HttpResponse(status=200)

    logger.info(
        "github_check_run_unacceptable_conclusion",
        conclusion=conclusion,
        check_run_name=check_run.name,
    )
    if not pr_url:
        return HttpResponse(status=200)

    task_run = find_task_run(pr_url=pr_url, branch=None)
    if not task_run:
        return HttpResponse(status=200)

    task_run.emit_console_event("info", f"Check run '{check_run.name}' completed with conclusion: {conclusion}")
    task_run.capture_event("check_run_completed", {"check_run_name": check_run.name, "conclusion": conclusion})
    message = (
        f"[GitHub check run failed] `{check_run.name}` completed with conclusion: {conclusion}.\n"
        "Inspect the failing check and address the underlying issue."
    )
    _forward_comment_to_task(task_run=task_run, pr_url=pr_url, message=message)
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


def _truncate_body(body: str | None) -> str:
    if not body:
        return ""
    if len(body) > MAX_COMMENT_BODY_LENGTH:
        return body[:MAX_COMMENT_BODY_LENGTH] + "\n\n[... truncated ...]"
    return body


def _format_comment_message(event: CommentEvent, event_type: str) -> str:
    """Build the message we forward to the agent for a single comment event.

    Includes author, path/line/diff context for review comments, and a
    bounded copy of the body. Returns an empty string when the comment is
    unusable (no body, no comment object).
    """
    comment: Comment | None = event.comment
    if comment is None and event.review is not None:
        # `pull_request_review` events use `review`, not `comment`; reuse the
        # same shape so the formatter has one path.
        comment = Comment(body=event.review.body, user=event.review.user)
    if comment is None:
        return ""

    body = _truncate_body(comment.body)
    if not body:
        return ""

    login = (comment.user.login if comment.user else None) or "reviewer"

    if event_type == "pull_request_review_comment" and comment.path:
        line = comment.line
        header_line = f" (line {line})" if line is not None else ""
        header = f"[GitHub Review Comment from @{login} on `{comment.path}`{header_line}]"
        diff = comment.diff_hunk or ""
        if diff:
            return f"{header}\n\n```diff\n{diff}\n```\n\n{body}"
        return f"{header}\n\n{body}"

    if event_type == "pull_request_review":
        return f"[GitHub Review from @{login}]\n\n{body}"

    return f"[GitHub Comment from @{login}]\n\n{body}"


def _handle_comment_event(event: CommentEvent, event_type: str = "issue_comment") -> HttpResponse:
    if event.action != "created":
        return HttpResponse(status=200)

    # Bot/system comments cause feedback loops if forwarded — Greptile, Copilot,
    # and our own auto-resume bot would all keep nudging each other.
    comment = event.comment
    if comment is not None:
        author_type = comment.user.type if comment.user else None
        if author_type in IGNORED_COMMENT_USER_TYPES:
            return HttpResponse(status=200)

    review = event.review
    if review is not None:
        review_author_type = review.user.type if review.user else None
        if review_author_type in IGNORED_COMMENT_USER_TYPES:
            return HttpResponse(status=200)

    # `issue_comment` fires for issues too — only PR comments have
    # `issue.pull_request`. Skip non-PR issue comments before doing any work.
    pull_request = event.pull_request or (event.issue.pull_request if event.issue else None)
    if not pull_request:
        return HttpResponse(status=200)

    pr_url = pull_request.html_url
    if not pr_url:
        return HttpResponse(status=200)

    branch = pull_request.head.ref
    task_run = find_task_run(pr_url=pr_url, branch=branch)
    if not task_run:
        logger.debug("github_comment_webhook_no_task_run", pr_url=pr_url)
        return HttpResponse(status=200)

    message = _format_comment_message(event, event_type=event_type)
    if not message:
        return HttpResponse(status=200)

    _forward_comment_to_task(task_run=task_run, pr_url=pr_url, message=message)
    return HttpResponse(status=200)


def _forward_comment_to_task(task_run: TaskRun, pr_url: str, message: str) -> None:
    """Forward an inbound comment/check_run event to the task's agent.

    Routes to the running workflow if there is one; falls back to a fresh
    resume run otherwise. Honors the auto-resume feature flag and respects
    the resume cooldown / cap.
    """
    user: User | None = task_run.task.created_by
    if not user:
        logger.warning(
            "github_comment_webhook_no_user",
            pr_url=pr_url,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
        )
        return
    if not user.distinct_id:
        logger.warning(
            "github_comment_webhook_user_missing_distinct_id",
            pr_url=pr_url,
            task_id=str(task_run.task_id),
            run_id=str(task_run.id),
            user_id=user.pk,
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
    task_run.emit_console_event("info", f"New activity on PR: {pr_url}")
    task_run.capture_event("pr_comment_received", {"pr_url": pr_url})

    # `is_terminal` only reflects TaskRun.status — the underlying Temporal
    # workflow may have already exited (inactivity timeout, worker crash,
    # status-update activity exhausted retries) while the row still says
    # IN_PROGRESS. If the signal can't reach a live workflow, fall through
    # and start a fresh run instead of silently dropping the comment.
    if not task_run.is_terminal and _signal_running_workflow(task_run, message):
        return
    _create_resume_run(task_run, message, pr_url)


def _signal_running_workflow(task_run: TaskRun, message: str) -> bool:
    """Signal the running workflow with a `pr_event` and the comment message.

    Returns True if the signal was delivered. Returns False if the workflow
    is unreachable (not found, already completed, or Temporal errored) — the
    caller should fall through to creating a new resume run.
    """
    from temporalio.service import RPCError, RPCStatusCode

    try:
        client = sync_connect()
        handle = client.get_workflow_handle(task_run.workflow_id)

        asyncio.run(handle.signal(ProcessTaskWorkflow.pr_event, message))

        logger.info(
            "github_comment_signaled_workflow",
            run_id=str(task_run.id),
            workflow_id=task_run.workflow_id,
        )
        return True
    except RPCError as e:
        # NOT_FOUND: workflow never started or already aged out of retention.
        # FAILED_PRECONDITION: workflow already in a terminal execution state.
        if e.status in (RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION):
            logger.info(
                "github_comment_workflow_unreachable",
                run_id=str(task_run.id),
                workflow_id=task_run.workflow_id,
                rpc_status=e.status.name,
            )
            return False
        logger.warning(
            "github_comment_signal_failed",
            run_id=str(task_run.id),
            error=str(e),
        )
        return False
    except Exception as e:
        logger.warning(
            "github_comment_signal_failed",
            run_id=str(task_run.id),
            error=str(e),
        )
        return False


def _create_resume_run(task_run: TaskRun, message: str, pr_url: str) -> None:
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

    # Cooldown: at most one resume run per task per RESUME_COOLDOWN window.
    # A burst of webhooks (CI fan-out, rapid comments) collapses to one run.
    cooldown_key = f"tasks:resume_cooldown:{task.id}"
    if not cache.add(cooldown_key, True, timeout=int(RESUME_COOLDOWN.total_seconds())):
        logger.info(
            "github_comment_resume_cooldown_active",
            task_id=str(task.id),
            run_id=str(task_run.id),
        )
        return

    # Hard cap on the absolute number of resume runs spawned from a single base
    # run, regardless of timing — a defense-in-depth check against attackers
    # who pace comments to defeat the cooldown.
    existing_resumes = TaskRun.objects.filter(state__resume_from_run_id=str(task_run.id)).count()
    if existing_resumes >= MAX_RESUMES:
        logger.info(
            "github_comment_resume_limit_reached",
            task_id=str(task.id),
            run_id=str(task_run.id),
            existing_resumes=existing_resumes,
            max_resumes=MAX_RESUMES,
        )
        return

    snapshot_ext_id = (task_run.state or {}).get("snapshot_external_id")

    if pr_url:
        contextualized_message = (
            f"[CONTEXT: This task already has an open pull request: {pr_url}\n"
            f"Check out the existing PR branch with `gh pr checkout {pr_url}`, "
            "make your changes, commit, and push to that branch. "
            "Do NOT create a new branch or PR. Inspect the PR and address any new findings]\n\n"
            f"{message}"
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
