import json
import asyncio
import logging

from django.conf import settings

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

_CLOUD_REPOSITORY = "posthog/posthog"
_LOCAL_REPOSITORY = "sortafreel/posthog"
ORIGIN_PRODUCT = "user_created"

POLL_INTERVAL_SECONDS = 10
MAX_POLL_SECONDS = 30 * 60  # 30 minutes (matches sandbox TTL)

# Cloud defaults (used when DEBUG=False)
_CLOUD_TEAM_ID = 2
_CLOUD_USER_ID = 196695
_CLOUD_GITHUB_INTEGRATION_ID = 155750


def _get_defaults() -> tuple[int, int, int, str]:
    """Return (team_id, user_id, github_integration_id, repository) based on environment."""
    if settings.DEBUG:
        from posthog.models.integration import Integration
        from posthog.models.team.team import Team
        from posthog.models.user import User

        team = Team.objects.first()
        if not team:
            raise RuntimeError("No team found in local database")

        user = User.objects.first()
        if not user:
            raise RuntimeError("No user found in local database")

        gh = Integration.objects.filter(team=team, kind="github").first()
        if not gh:
            raise RuntimeError(
                f"No GitHub integration found for team {team.id}. "
                "Set up a GitHub App installation first: "
                "go to /settings/integrations in your local PostHog."
            )

        return team.id, user.id, gh.id, _LOCAL_REPOSITORY

    return _CLOUD_TEAM_ID, _CLOUD_USER_ID, _CLOUD_GITHUB_INTEGRATION_ID, _CLOUD_REPOSITORY


async def run_review(prompt: str, branch: str = "master") -> str:
    """Spawn a sandbox agent with the given prompt and return its last response.

    Creates a Task + TaskRun, triggers the existing Temporal workflow,
    polls until completion, then reads the S3 logs and extracts the last
    agent message.
    """
    full_description = _build_description(prompt, branch)
    task, task_run = await _create_task_and_trigger(full_description)
    logger.info("review_hog: started task=%s run=%s", task.id, task_run.id)
    final_status, last_message = await _poll_until_done(task_run)
    logger.info("review_hog: finished run=%s status=%s", task_run.id, final_status)
    if not last_message:
        return f"[review_hog] Run completed with status={final_status} but no agent message found."
    return last_message


def _build_description(prompt: str, branch: str) -> str:
    if branch and branch != "master":
        return (
            f"First, in the repository at /tmp/workspace/repos/posthog/posthog, "
            f"run: git fetch origin {branch} && git checkout {branch}\n\n"
            f"Then:\n\n{prompt}"
        )
    return prompt


async def _create_task_and_trigger(description: str):
    from products.tasks.backend.models import Task
    from products.tasks.backend.temporal.client import execute_task_processing_workflow

    team_id, user_id, github_integration_id, repository = await sync_to_async(_get_defaults)()

    task = await sync_to_async(Task.objects.create)(
        team_id=team_id,
        created_by_id=user_id,
        title=description[:100],
        description=description,
        origin_product=ORIGIN_PRODUCT,
        github_integration_id=github_integration_id,
        repository=repository,
    )

    task_run = await sync_to_async(task.create_run)(mode="background")

    await sync_to_async(execute_task_processing_workflow)(
        task_id=str(task.id),
        run_id=str(task_run.id),
        team_id=team_id,
        user_id=user_id,
    )

    return task, task_run


async def _poll_until_done(task_run) -> tuple[str, str | None]:
    """Poll logs for agent completion, fall back to TaskRun status.

    Returns (status, last_agent_message). The agent emits a log entry with
    stopReason=end_turn when it finishes — we detect that instead of waiting
    for the Temporal workflow's 5-min inactivity timeout.
    """
    from products.tasks.backend.models import TaskRun

    elapsed = 0
    while elapsed < MAX_POLL_SECONDS:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

        finished, last_message = await sync_to_async(_check_logs)(task_run)
        if finished:
            return "completed", last_message

        refreshed = await sync_to_async(TaskRun.objects.get)(id=task_run.id)
        if refreshed.status in {
            TaskRun.Status.COMPLETED,
            TaskRun.Status.FAILED,
            TaskRun.Status.CANCELLED,
        }:
            _, last_message = await sync_to_async(_check_logs)(task_run)
            return refreshed.status, last_message

    return "timeout", None


def _check_logs(task_run) -> tuple[bool, str | None]:
    """Parse S3 logs. Returns (agent_finished, last_agent_message)."""
    from posthog.storage import object_storage

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if not log_content.strip():
        return False, None

    latest_text: str | None = None
    agent_finished = False

    for line in log_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue

        result = notification.get("result")
        if isinstance(result, dict) and result.get("stopReason") == "end_turn":
            agent_finished = True

        if notification.get("method") != "session/update":
            continue

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue

        if update.get("sessionUpdate") not in {"agent_message", "agent_message_chunk"}:
            continue

        text = _extract_text(update)
        if text:
            latest_text = text

    return agent_finished, latest_text


def _extract_text(update: dict) -> str | None:
    content = update.get("content")
    if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
        candidate = content["text"].strip()
        if candidate:
            return candidate

    message = update.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    return None
