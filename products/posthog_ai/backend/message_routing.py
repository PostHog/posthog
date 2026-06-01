"""In-process routing for sandbox-runtime conversation messages.

Entry point for the non-streaming `POST /conversations/{id}/sandbox/` endpoint.
Wraps + dedupes the user message, then starts a `products/tasks` Run (first
message), signals a follow-up on the in-progress Run, or resumes into a new Run
after a terminal Run — all via direct Python calls, never HTTP-to-self and never
a Django SSE relay.

See `docs/internal/posthog-ai-migration/02_CORE.md` §§ 3, 4, 5.1–5.4 and
`01_CONTEXT.md` § 4.
"""

import json
from typing import TYPE_CHECKING, Any, cast

from django.db import transaction

import structlog
from asgiref.sync import async_to_sync
from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.event_usage import report_user_action
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.storage import object_storage

from products.posthog_ai.backend.context_wrapper import (
    ALLOWED_TYPES,
    MAX_ATTACHED_ITEMS,
    MAX_TEXT_LENGTH,
    AttachedContext,
    prune_repeated_entity_refs,
    wrap_user_message,
)
from products.posthog_ai.backend.system_prompt import build_posthog_ai_system_prompt
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.agent_command import send_cancel
from products.tasks.backend.temporal.client import execute_task_processing_workflow, signal_task_followup_message

if TYPE_CHECKING:
    from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

# Entity types whose id must be an integer (vs short_id / UUID strings).
_INTEGER_ID_TYPES: frozenset[str] = frozenset({"dashboard", "action"})

# Run statuses that accept a follow-up signal without creating a successor Run.
_IN_PROGRESS_STATUSES: frozenset[str] = frozenset({TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS})


def handle_sandbox_message(request: Request, conversation: "Conversation") -> Response:
    """Route a sandbox-runtime message to a products/tasks Run, in-process.

    Branches on the conversation's current Run (02_CORE § 4):
    - No Task yet → first message creates the Task + Run.
    - Current Run in-progress → signal a follow-up onto the live Run.
    - Current Run terminal → resume into a brand-new successor Run.
    """
    team = conversation.team
    user = cast(User, request.user)

    content = request.data.get("content")
    if not isinstance(content, str) or not content.strip():
        raise exceptions.ValidationError("`content` is required.")

    trace_id = request.data.get("trace_id")
    attached_context = _validate_attached_context(request.data.get("attached_context"))

    if conversation.task_id is None:
        return _handle_first_message(
            request=request,
            conversation=conversation,
            team=team,
            user=user,
            content=content,
            trace_id=trace_id,
            attached_context=attached_context,
        )

    current_run = conversation.current_run
    if current_run is None:
        # The Task lost all of its Runs (e.g. cleanup) — there is nothing to
        # follow up on or resume from. Surface a recoverable error.
        raise exceptions.ValidationError("This conversation has no active run to continue.")

    # Dedupe against every entity already named earlier in the conversation.
    prior_seen = _collect_seen_entity_refs(current_run)
    deduped = prune_repeated_entity_refs(attached_context, prior=prior_seen)
    wrapped = wrap_user_message(content, deduped)

    if current_run.status in _IN_PROGRESS_STATUSES:
        return _handle_in_progress_followup(
            request=request,
            conversation=conversation,
            team=team,
            user=user,
            run=current_run,
            wrapped=wrapped,
            trace_id=trace_id,
            attached_context=attached_context,
        )

    return _handle_terminal_resume(
        request=request,
        conversation=conversation,
        team=team,
        user=user,
        run=current_run,
        wrapped=wrapped,
        trace_id=trace_id,
        attached_context=attached_context,
    )


def _handle_first_message(
    *,
    request: Request,
    conversation: "Conversation",
    team: Team,
    user: User,
    content: str,
    trace_id: str | None,
    attached_context: list[AttachedContext],
) -> Response:
    # First turn — the prior-seen set is empty, so dedupe is a no-op.
    deduped = prune_repeated_entity_refs(attached_context, prior=[])
    wrapped = wrap_user_message(content, deduped)

    system_prompt = async_to_sync(build_posthog_ai_system_prompt)(team, user)

    task = Task.create_and_run(
        team=team,
        title=content[:80],
        description=content,
        origin_product=Task.OriginProduct.POSTHOG_AI,
        user_id=user.pk,
        repository=None,
        create_pr=False,
        mode="interactive",
        initial_permission_mode="default",
        # Defer the workflow so the initial run state can carry the PostHog AI keys.
        start_workflow=False,
    )

    task_run = task.latest_run
    if task_run is None:
        raise exceptions.ValidationError("Failed to create sandbox task run.")

    # Enrich the initial run state with the PostHog AI per-Run keys, then start the
    # workflow. `attached_context` stores the full, undeduped list (01_CONTEXT § 4.1).
    run_state: dict[str, Any] = dict(task_run.state or {})
    run_state.update(
        {
            "systemPrompt": system_prompt,
            "attached_context": attached_context,
            "initial_permission_mode": "default",
            "pending_user_message": wrapped,
        }
    )
    task_run.state = run_state
    task_run.save(update_fields=["state"])

    with transaction.atomic():
        conversation.task = task
        conversation.save(update_fields=["task", "updated_at"])

    # Side effects after the commit: start the run, then emit telemetry.
    execute_task_processing_workflow(
        task_id=str(task.id),
        run_id=str(task_run.id),
        team_id=team.id,
        user_id=user.pk,
        create_pr=False,
    )

    report_user_action(
        user,
        "prompt sent",
        {
            "trace_id": trace_id,
            "conversation_id": str(conversation.id),
            "execution_type": "sandbox",
            "just_created_run": True,
        },
        team=team,
        request=request,
    )

    return Response(
        {
            "task_id": str(task.id),
            "run_id": str(task_run.id),
            "trace_id": trace_id,
            "run_status": task_run.status,
            "just_created_run": True,
        },
        status=status.HTTP_200_OK,
    )


def _handle_in_progress_followup(
    *,
    request: Request,
    conversation: "Conversation",
    team: Team,
    user: User,
    run: TaskRun,
    wrapped: str,
    trace_id: str | None,
    attached_context: list[AttachedContext],
) -> Response:
    """Follow-up while the current Run is queued / in-progress (02_CORE § 5.2).

    Signal the live Temporal workflow in-process — no new Run, no SSE re-open.
    The full undeduped context is recorded on the logged message's
    `_meta.attached_context` (01_CONTEXT § 4.1) so the persisted ACP log stays
    a complete record.
    """
    signal_task_followup_message(run.workflow_id, wrapped, artifact_ids=[])

    _log_user_message(run, wrapped, attached_context)

    report_user_action(
        user,
        "prompt sent",
        {
            "trace_id": trace_id,
            "conversation_id": str(conversation.id),
            "execution_type": "sandbox",
            "just_created_run": False,
        },
        team=team,
        request=request,
    )

    return Response(
        {
            "task_id": str(conversation.task_id),
            "run_id": str(run.id),
            "trace_id": trace_id,
            "run_status": run.status,
            "just_created_run": False,
        },
        status=status.HTTP_200_OK,
    )


def _handle_terminal_resume(
    *,
    request: Request,
    conversation: "Conversation",
    team: Team,
    user: User,
    run: TaskRun,
    wrapped: str,
    trace_id: str | None,
    attached_context: list[AttachedContext],
) -> Response:
    """Follow-up after the current Run reached a terminal status (02_CORE § 5.3).

    Resume into a brand-new successor Run on the same Task, then start its
    workflow. `current_run` resolves to the new Run via the Task's reverse
    relation — the conversation's `task` FK is unchanged.
    """
    task = conversation.task
    if task is None:
        raise exceptions.ValidationError("This conversation has no backing task to resume.")

    system_prompt = async_to_sync(build_posthog_ai_system_prompt)(team, user)

    extra_state: dict[str, Any] = {
        "resume_from_run_id": str(run.id),
        "pending_user_message": wrapped,
        "systemPrompt": system_prompt,
        # The full, undeduped list — survives for the life of the new Run.
        "attached_context": attached_context,
        "initial_permission_mode": "default",
    }
    # Carry the prior Run's snapshot forward so the resume reuses its filesystem.
    snapshot_external_id = (run.state or {}).get("snapshot_external_id")
    if snapshot_external_id:
        extra_state["snapshot_external_id"] = snapshot_external_id

    new_run = task.create_run(mode="interactive", extra_state=extra_state)

    execute_task_processing_workflow(
        task_id=str(task.id),
        run_id=str(new_run.id),
        team_id=team.id,
        user_id=user.pk,
        create_pr=False,
    )

    report_user_action(
        user,
        "prompt sent",
        {
            "trace_id": trace_id,
            "conversation_id": str(conversation.id),
            "execution_type": "sandbox",
            "just_created_run": True,
        },
        team=team,
        request=request,
    )

    return Response(
        {
            "task_id": str(task.id),
            "run_id": str(new_run.id),
            "trace_id": trace_id,
            "run_status": new_run.status,
            "just_created_run": True,
        },
        status=status.HTTP_200_OK,
    )


def handle_sandbox_cancel(conversation: "Conversation") -> Response:
    """Cancel the conversation's current sandbox Run in-process (02_CORE § 5.4).

    Delegates to the products/tasks command path with `{"method": "cancel"}` —
    the same control command PostHog Code issues. Returns the resulting
    `run_status`; the frontend SSE then receives a terminal `task_run_state`.
    """
    if conversation.task_id is None:
        raise exceptions.ValidationError("This conversation has no backing task to cancel.")

    run = conversation.current_run
    if run is None:
        raise exceptions.ValidationError("This conversation has no active run to cancel.")

    if run.is_terminal:
        # Nothing to cancel — report the already-terminal status idempotently.
        return Response(
            {"task_id": str(conversation.task_id), "run_id": str(run.id), "run_status": run.status},
            status=status.HTTP_200_OK,
        )

    # Delegate to the products/tasks command path in-process. `send_cancel` is the
    # same `{"method": "cancel"}` control command the `POST /runs/{id}/command/`
    # action forwards to the sandbox agent server.
    send_cancel(run)
    run.refresh_from_db(fields=["status"])

    return Response(
        {"task_id": str(conversation.task_id), "run_id": str(run.id), "run_status": run.status},
        status=status.HTTP_200_OK,
    )


def _collect_seen_entity_refs(run: TaskRun) -> list[tuple[str, str | int]]:
    """Collect `(type, id)` pairs for entities already named in the conversation.

    Walks the Run's `state.attached_context` (the first message's full list) plus
    every prior `_posthog/user_message` log entry's `_meta.attached_context`
    across the entire resume chain (01_CONTEXT §§ 4.1, dedupe lifetime-wide). One
    S3 read per chain run; `text` items are never deduped so they're skipped.
    """
    seen: list[tuple[str, str | int]] = []

    def _absorb(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            item_id = item.get("id")
            if item_type in ALLOWED_TYPES and item_type != "text" and item_id is not None:
                seen.append((item_type, item_id))

    for chain_run in run.get_resume_chain():
        _absorb((chain_run.state or {}).get("attached_context"))
        log_content = object_storage.read(chain_run.log_url, missing_ok=True) or ""
        for line in log_content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            notification = entry.get("notification") if isinstance(entry, dict) else None
            if not isinstance(notification, dict):
                continue
            if notification.get("method") != "_posthog/user_message":
                continue
            params = notification.get("params")
            meta = params.get("_meta") if isinstance(params, dict) else None
            if isinstance(meta, dict):
                _absorb(meta.get("attached_context"))

    return seen


def _log_user_message(run: TaskRun, wrapped: str, attached_context: list[AttachedContext]) -> None:
    """Append a `_posthog/user_message` entry to the Run's ACP log (01_CONTEXT § 4.1).

    Records the wrapped content plus the full undeduped `attached_context` under
    `_meta` so the persisted log is a complete per-message record that
    `_collect_seen_entity_refs` reads on later follow-ups.
    """
    entry = {
        "notification": {
            "method": "_posthog/user_message",
            "params": {
                "content": wrapped,
                "_meta": {"attached_context": attached_context},
            },
        }
    }
    run.append_log([entry])


def _validate_attached_context(raw: Any) -> list[AttachedContext]:
    """Validate user-supplied attached context at the boundary (01_CONTEXT § 4.4).

    Existence is intentionally NOT validated — the agent's read tool surfaces a
    missing-row error naturally, which is cheaper than a sync DB lookup per submit.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise exceptions.ValidationError("`attached_context` must be a list.")
    if len(raw) > MAX_ATTACHED_ITEMS:
        raise exceptions.ValidationError(f"`attached_context` cannot exceed {MAX_ATTACHED_ITEMS} items.")

    validated: list[AttachedContext] = []
    for item in raw:
        if not isinstance(item, dict):
            raise exceptions.ValidationError("Each `attached_context` item must be an object.")
        item_type = item.get("type")
        if item_type not in ALLOWED_TYPES:
            raise exceptions.ValidationError(f"Unsupported attached_context type: {item_type!r}.")

        if item_type == "text":
            value = item.get("value")
            if not isinstance(value, str):
                raise exceptions.ValidationError("`text` attachments require a string `value`.")
            if len(value) > MAX_TEXT_LENGTH:
                raise exceptions.ValidationError(f"`text` value cannot exceed {MAX_TEXT_LENGTH} characters.")
            validated.append(cast(AttachedContext, {"type": "text", "value": value}))
            continue

        item_id = item.get("id")
        item_id = _validate_entity_id(item_type, item_id)
        entity: AttachedContext = {"type": item_type, "id": item_id}
        name = item.get("name")
        if isinstance(name, str) and name:
            entity["name"] = name
        validated.append(entity)

    return validated


def _validate_entity_id(item_type: str, item_id: Any) -> str | int:
    if item_type in _INTEGER_ID_TYPES:
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            raise exceptions.ValidationError(f"`{item_type}` id must be an integer.")
        return item_id

    if not isinstance(item_id, str) or not item_id:
        raise exceptions.ValidationError(f"`{item_type}` id must be a non-empty string.")
    return item_id
