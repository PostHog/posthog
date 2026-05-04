import hmac
import json
import uuid
import hashlib

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.instance_setting import get_instance_setting

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


@csrf_exempt
def github_pr_webhook(request: HttpRequest) -> HttpResponse:
    """
    Handle GitHub pull_request webhook events.

    This endpoint:
    1. Validates the HMAC-SHA256 signature from GitHub
    2. Parses pull_request events (opened, closed, merged)
    3. Finds TaskRun by matching pr_url in output field
    4. Emits console log events and analytics

    Expected events:
    - pull_request.opened → log "PR created"
    - pull_request.closed with merged=true → log "PR merged"
    - pull_request.closed with merged=false → log "PR closed"
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
    if event_type != "pull_request":
        # Not a PR event, acknowledge but don't process, shouldnt happen becuase of github app permissions
        return HttpResponse(status=200)

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
        # Other actions (reopened, edited, etc.) - acknowledge but don't process
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

    return HttpResponse(status=200)
