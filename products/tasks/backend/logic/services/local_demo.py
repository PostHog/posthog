import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from posthog.local_demo import require_local_development
from posthog.models import OrganizationMembership, Team
from posthog.storage import object_storage

from products.tasks.backend.facade.local_demo_contracts import LocalDemoTask, local_demo_task_ids
from products.tasks.backend.models import Task, TaskRun


def _conversation_log() -> str:
    messages = [
        ("user_message", "What should I check before trying the demo signup flow?"),
        (
            "agent_message",
            "Start with the welcome page, submit the signup form, then open the confirmation screen. "
            "Check that the form explains missing fields and that returning to it preserves your entries. "
            "This is a saved demo conversation; no agent was run.",
        ),
    ]
    entries: list[dict[str, object]] = [
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": role,
                        "content": {"type": "text", "text": text},
                    }
                },
            }
        }
        for role, text in messages
    ]
    entries.append({"notification": {"result": {"stopReason": "end_turn"}}})
    return "".join(json.dumps(entry) + "\n" for entry in entries)


def _has_conversation(content: str) -> bool:
    roles: set[str] = set()
    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            return False
        if not isinstance(entry, dict):
            return False
        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue
        params = notification.get("params")
        if not isinstance(params, dict):
            continue
        update = params.get("update")
        if not isinstance(update, dict):
            continue
        role = update.get("sessionUpdate")
        message = update.get("content")
        if not isinstance(role, str) or role not in {"user_message", "agent_message"} or not isinstance(message, dict):
            continue
        text = message.get("text")
        if message.get("type") == "text" and isinstance(text, str) and text.strip():
            roles.add(role)
    return roles == {"user_message", "agent_message"}


def _ensure_conversation_log(log_url: str) -> None:
    if (
        not settings.OBJECT_STORAGE_ENABLED
        or not object_storage.is_usable_endpoint(settings.OBJECT_STORAGE_ENDPOINT)
        or not settings.OBJECT_STORAGE_BUCKET
    ):
        raise ValueError(
            "Local demo chats require object storage. Enable OBJECT_STORAGE_ENABLED, configure its local endpoint "
            "and bucket, start the local object storage service, then retry."
        )
    expected: str | None = None
    try:
        persisted = object_storage.read(log_url, missing_ok=True)
        if persisted is None:
            expected = _conversation_log()
            object_storage.write(log_url, expected)
            persisted = object_storage.read(log_url, missing_ok=True)
    except Exception as error:
        raise ValueError(
            "Could not read or save the local demo chat. Start the local object storage service and check its "
            "endpoint, bucket and credentials, then retry."
        ) from error
    if expected is not None and persisted != expected:
        raise ValueError(
            "Local object storage did not persist the demo chat log. Check OBJECT_STORAGE_ENABLED, start the "
            "local object storage service, then retry."
        )
    if persisted is None or not _has_conversation(persisted):
        raise ValueError(
            "The saved local demo chat log has no readable conversation. Its contents were preserved; repair "
            "the saved log before retrying."
        )


def seed_local_demo_task(*, team_id: int, user_id: int) -> LocalDemoTask:
    """Insert a completed local conversation without workflow, telemetry or notification hooks.

    Bulk inserts intentionally bypass model save signals. A readable transcript must exist
    before rows are inserted. Re-running repairs a missing log while preserving existing edits.
    """
    require_local_development()
    team = Team.objects.get(id=team_id)
    if not OrganizationMembership.objects.filter(organization_id=team.organization_id, user_id=user_id).exists():
        raise ValueError("The selected user must belong to the project's organization")

    ids = local_demo_task_ids(team_id=team_id, user_id=user_id)
    demo_task = Task(
        id=ids.task_id,
        team=team,
        created_by_id=user_id,
        title="Demo: review the signup checklist",
        description="Summarize a small signup checklist for this local demo project.",
        origin_product=Task.OriginProduct.USER_CREATED,
        origin_key=f"local-inbox-demo:v1:{user_id}:chat",
        state={"local_demo": True},
    )
    demo_run = TaskRun(
        id=ids.run_id,
        task=demo_task,
        team_id=team_id,
        origin_product=demo_task.origin_product,
        status=TaskRun.Status.COMPLETED,
        environment=TaskRun.Environment.LOCAL,
        stage="research",
        completed_at=timezone.now(),
        state={"local_demo": True},
    )
    _ensure_conversation_log(demo_run.log_url)

    with transaction.atomic():
        demo_task._assign_task_number()
        Task.objects.bulk_create([demo_task], ignore_conflicts=True)
        demo_run.task = Task.objects.get(id=ids.task_id, team_id=team_id, created_by_id=user_id)
        TaskRun.objects.bulk_create([demo_run], ignore_conflicts=True)
        TaskRun.objects.get(id=ids.run_id, task_id=ids.task_id, team_id=team_id)
    return ids
