import json
import asyncio
import logging

from django.conf import settings

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

ORIGIN_PRODUCT = "user_created"

# Sandbox logs polling from S3
POLL_INTERVAL_SECONDS = 10
MAX_POLL_SECONDS = 30 * 60  # 30 minutes (matches sandbox TTL)

# Local defaults (used when DEBUG=True)
_LOCAL_REPOSITORY = "sortafreel/posthog"

# Cloud defaults (used when DEBUG=False)
_CLOUD_REPOSITORY = "posthog/posthog"
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

        return team.id, user.id, gh.id, _LOCAL_REPOSITORY  # type: ignore

    return _CLOUD_TEAM_ID, _CLOUD_USER_ID, _CLOUD_GITHUB_INTEGRATION_ID, _CLOUD_REPOSITORY


async def run_prompt(prompt: str, branch: str = "master", step_name: str = "") -> tuple[str, str]:
    """Spawn a sandbox agent with the given prompt and return its last response and full logs"""
    task, task_run = await _create_task_and_trigger(prompt, branch, step_name)
    logger.info("sandbox_custom_prompt: started task=%s run=%s step=%s", task.id, task_run.id, step_name or "unknown")
    final_status, last_message, full_log = await _poll_until_done(task_run)
    logger.info("sandbox_custom_prompt: finished run=%s status=%s", task_run.id, final_status)
    if not last_message:
        last_message = f"[sandbox_custom_prompt] Run completed with status={final_status} but no agent message found."
    return last_message, full_log or ""


async def _create_task_and_trigger(description: str, branch: str = "master", step_name: str = ""):
    from products.tasks.backend.models import Task
    from products.tasks.backend.temporal.client import execute_task_processing_workflow

    team_id, user_id, github_integration_id, repository = await sync_to_async(_get_defaults)()
    title = f"[sandbox_custom_prompt:{step_name}] {description[:80]}" if step_name else description[:100]
    task = await sync_to_async(Task.objects.create)(
        team_id=team_id,
        created_by_id=user_id,
        title=title,
        description=description,
        origin_product=ORIGIN_PRODUCT,
        github_integration_id=github_integration_id,
        repository=repository,
    )
    task_run = await sync_to_async(task.create_run)(mode="background")
    if branch and branch != "master":
        task_run.branch = branch
        await sync_to_async(task_run.save)(update_fields=["branch"])
    await sync_to_async(execute_task_processing_workflow)(
        task_id=str(task.id),
        run_id=str(task_run.id),
        team_id=team_id,
        user_id=user_id,
    )
    return task, task_run


async def _poll_until_done(task_run) -> tuple[str, str | None, str | None]:
    """Poll logs for agent completion, fall back to TaskRun status."""
    from products.tasks.backend.models import TaskRun

    printed_lines = 0
    elapsed = 0
    while elapsed < MAX_POLL_SECONDS:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        finished, last_message, full_log = await sync_to_async(_check_logs)(task_run)
        printed_lines = _stream_new_lines(full_log, printed_lines)
        if finished:
            return "completed", last_message, full_log
        refreshed = await sync_to_async(TaskRun.objects.get)(id=task_run.id)
        if refreshed.status in {
            TaskRun.Status.COMPLETED,
            TaskRun.Status.FAILED,
            TaskRun.Status.CANCELLED,
        }:
            _, last_message, full_log = await sync_to_async(_check_logs)(task_run)
            printed_lines = _stream_new_lines(full_log, printed_lines)
            return refreshed.status, last_message, full_log
    return "timeout", None, None


def _stream_new_lines(full_log: str | None, printed_lines: int) -> int:
    """Print new agent message lines from logs, return updated line count."""
    if not full_log:
        return printed_lines
    lines = full_log.strip().split("\n")
    for line in lines[printed_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        notification = entry.get("notification")
        if not isinstance(notification, dict) or notification.get("method") != "session/update":
            continue
        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        text = _extract_text(update)
        if text:
            logger.info(text)
    return len(lines)


def _check_logs(task_run) -> tuple[bool, str | None, str | None]:
    """Parse S3 logs. Returns (agent_finished, last_agent_message, full_log_content)."""
    from posthog.storage import object_storage

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if not log_content.strip():
        return False, None, None
    agent_finished = False
    # Collect all parsed session updates so we can walk backwards at the end.
    parsed_updates: list[dict] = []
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
        parsed_updates.append(update)
    # Walk backwards from the end to find the final agent response.
    # First, skip non-agent entries (e.g. usage_update) to find the last
    # agent message. Then collect consecutive agent messages until we hit
    # something else — the agent sometimes splits its response across entries.
    _AGENT_MSG_TYPES = {"agent_message", "agent_message_chunk"}
    trailing_parts: list[str] = []
    found_agent_msg = False
    for update in reversed(parsed_updates):
        is_agent_msg = update.get("sessionUpdate") in _AGENT_MSG_TYPES
        if not found_agent_msg:
            if is_agent_msg:
                found_agent_msg = True
            else:
                continue
        if found_agent_msg and not is_agent_msg:
            break
        text = _extract_text(update)
        if text:
            trailing_parts.append(text)
    trailing_parts.reverse()
    latest_text = "".join(trailing_parts) if trailing_parts else None
    return agent_finished, latest_text, log_content


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
