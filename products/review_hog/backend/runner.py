import json
import asyncio
import logging

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

TEAM_ID = 2
USER_ID = 196695
GITHUB_INTEGRATION_ID = 155750
REPOSITORY = "posthog/posthog"
ORIGIN_PRODUCT = "user_created"

POLL_INTERVAL_SECONDS = 10
MAX_POLL_SECONDS = 30 * 60  # 30 minutes (matches sandbox TTL)


async def run_review(prompt: str, branch: str = "master") -> str:
    """Spawn a sandbox agent with the given prompt and return its last response."""
    full_description = _build_description(prompt, branch)
    task, task_run = await _create_task_and_trigger(full_description)
    logger.info("review_hog: started task=%s run=%s", task.id, task_run.id)
    final_status = await _poll_until_terminal(task_run)
    logger.info("review_hog: finished run=%s status=%s", task_run.id, final_status)
    last_message = await sync_to_async(_read_last_agent_message)(task_run)
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

    task = await sync_to_async(Task.objects.create)(
        team_id=TEAM_ID,
        created_by_id=USER_ID,
        title=description[:100],
        description=description,
        origin_product=ORIGIN_PRODUCT,
        github_integration_id=GITHUB_INTEGRATION_ID,
        repository=REPOSITORY,
    )

    task_run = await sync_to_async(task.create_run)(mode="background")

    await sync_to_async(execute_task_processing_workflow)(
        task_id=str(task.id),
        run_id=str(task_run.id),
        team_id=TEAM_ID,
        user_id=USER_ID,
    )

    return task, task_run


async def _poll_until_terminal(task_run) -> str:
    from products.tasks.backend.models import TaskRun

    elapsed = 0
    while elapsed < MAX_POLL_SECONDS:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

        refreshed = await sync_to_async(TaskRun.objects.get)(id=task_run.id)
        if refreshed.status in {
            TaskRun.Status.COMPLETED,
            TaskRun.Status.FAILED,
            TaskRun.Status.CANCELLED,
        }:
            return refreshed.status

    return "timeout"


def _read_last_agent_message(task_run) -> str | None:
    """Read S3 logs and extract the last agent_message text."""
    from posthog.storage import object_storage

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if not log_content.strip():
        return None

    latest_text: str | None = None

    for line in log_content.strip().split("\n"):
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

        if update.get("sessionUpdate") not in {"agent_message", "agent_message_chunk"}:
            continue

        text = _extract_text(update)
        if text:
            latest_text = text

    return latest_text


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
