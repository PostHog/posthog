"""Mirror a LangGraph conversation into the task world.

The new PostHog AI renders and resumes a chat from a task run's S3 log. A LangGraph conversation
stores its history in Postgres checkpoints instead, so nothing in the task world can see it. This
module keeps a task-world copy of every LangGraph conversation up to date: one Task, one completed
"import run" that never executed, and an S3 log written in the same wire format a real sandbox run
produces. The task viewer and the agent-server's resume path then treat the conversation exactly
like a native task.

The mirror runs after each completed LangGraph turn (see the chat agent workflow). It reads the
conversation's messages, reads how many were copied before (stored on the import run's state), and
appends the rest. A failed mirror is retried on the next turn from the same count, so it never has
to remember partial work.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

import structlog
from asgiref.sync import sync_to_async

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.facade import (
    api as tasks_facade,
    contracts as tasks_contracts,
)

logger = structlog.get_logger(__name__)

IMPORTED_FROM_CONVERSATION = "conversation"
# Run-state fields that record how far the conversation has been copied into the import run.
MESSAGES_COPIED_KEY = "conversation_messages_copied"
LAST_MESSAGE_ID_KEY = "conversation_last_message_id"
IMPORTED_TASK_ORIGIN_KEY_PREFIX = "phai-conversation:"

# The task thread and the agent-server both recognize a PostHog tool call by this Claude Code tool
# name; the inner tool is parsed out of the exec command. Legacy tool calls are written in the same
# shape so the product widgets (insight, recordings, ...) render them.
_EXEC_TOOL_META: dict[str, Any] = {"claudeCode": {"toolName": "mcp__posthog__exec"}}


@frozen
class CopyProgress:
    message_count: int
    last_message_id: str | None


@frozen
class MirrorResult:
    skipped_reason: str | None
    task_id: UUID | None
    run_id: UUID | None
    appended_frames: int


def origin_key_for_conversation(conversation_id: UUID | str) -> str:
    return f"{IMPORTED_TASK_ORIGIN_KEY_PREFIX}{conversation_id}"


def _frame(method: str, params: dict[str, Any]) -> dict[str, Any]:
    # LangGraph messages carry no time of their own, so copied lines carry no `timestamp`. The
    # thread renders no timing for them instead of a time we would have to invent.
    return {"type": "notification", "notification": {"jsonrpc": "2.0", "method": method, "params": params}}


def _session_update(session_id: str, update: dict[str, Any]) -> dict[str, Any]:
    return _frame("session/update", {"sessionId": session_id, "update": update})


def _text_content(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _tool_result_output(
    tool_message: dict[str, Any], artifact: dict[str, Any] | None, call_args: dict[str, Any]
) -> dict[str, Any]:
    text = tool_message.get("content") or ""
    output: dict[str, Any] = {"0": _text_content(text)}
    if artifact is not None:
        content = artifact.get("content") or {}
        output.update(
            {
                "artifact_id": artifact.get("artifact_id"),
                "query": content.get("query"),
                "name": content.get("name"),
                "description": content.get("description"),
                "content_type": content.get("content_type"),
            }
        )
    recordings_filters = call_args.get("recordings_filters")
    # RecordingsWidget renders a ready-made universal-filters object from rawOutput.filters.
    if isinstance(recordings_filters, dict) and "filter_group" in recordings_filters:
        output["filters"] = recordings_filters
    return output


def project_legacy_messages(
    messages: list[dict[str, Any]],
    *,
    run_id: str,
    include_run_start: bool,
) -> list[dict[str, Any]]:
    """Convert serialized LangGraph messages into task-run log frames.

    Frame shapes are copied from real sandbox run logs, because two consumers parse this log
    without knowing it was imported: the task thread projection (web) and the agent-server's resume
    parser. User turns use the `importedUserPrompt` convention that `TaskRun.clear_conversation`
    established for user text written without an agent. Every frame carries an `imported` marker so
    provenance stays visible in the data.
    """
    session_id = run_id
    frames: list[dict[str, Any]] = []
    if include_run_start:
        # Without a run_started frame the viewer keeps the run in its "provisioning" phase.
        frames.append(_frame("_posthog/run_started", {"runId": run_id, "imported": True}))

    pending_artifact: dict[str, Any] | None = None
    call_args_by_id: dict[str, dict[str, Any]] = {}
    turn_has_agent_output = False

    for message in messages:
        message_type = message.get("type")
        if message_type == "human":
            if turn_has_agent_output:
                frames.append(_frame("_posthog/turn_complete", {}))
                turn_has_agent_output = False
            frames.append(
                _session_update(
                    session_id,
                    {
                        "sessionUpdate": "user_message_chunk",
                        "content": _text_content(message.get("content") or ""),
                        "_meta": {"importedUserPrompt": True, "imported": True},
                    },
                )
            )
        elif message_type == "ai":
            for thought in (message.get("meta") or {}).get("thinking") or []:
                if thought.get("thinking"):
                    frames.append(
                        _session_update(
                            session_id,
                            {
                                "sessionUpdate": "agent_thought_chunk",
                                "content": _text_content(thought["thinking"]),
                                "_meta": {"imported": True},
                            },
                        )
                    )
            if message.get("content"):
                frames.append(
                    _session_update(
                        session_id,
                        {
                            "sessionUpdate": "agent_message",
                            "content": _text_content(message["content"]),
                            "_meta": {"imported": True},
                        },
                    )
                )
                turn_has_agent_output = True
            for tool_call in message.get("tool_calls") or []:
                args = tool_call.get("args") or {}
                call_args_by_id[tool_call["id"]] = args
                command = f"call {tool_call['name']} {json.dumps(args)}"
                base = {
                    "_meta": {**_EXEC_TOOL_META, "imported": True},
                    "toolCallId": tool_call["id"],
                    "title": "exec",
                    "kind": "other",
                    "content": [],
                }
                frames.append(
                    _session_update(
                        session_id,
                        {**base, "sessionUpdate": "tool_call", "rawInput": {}, "status": "pending"},
                    )
                )
                frames.append(
                    _session_update(
                        session_id,
                        {**base, "sessionUpdate": "tool_call_update", "rawInput": {"command": command}},
                    )
                )
                turn_has_agent_output = True
        elif message_type == "ai/artifact":
            # The artifact precedes the tool result that produced it; its query rides that result.
            pending_artifact = message
        elif message_type == "tool":
            tool_call_id = message["tool_call_id"]
            output = _tool_result_output(message, pending_artifact, call_args_by_id.get(tool_call_id, {}))
            pending_artifact = None
            frames.append(
                _session_update(
                    session_id,
                    {
                        "_meta": {**_EXEC_TOOL_META, "imported": True},
                        "toolCallId": tool_call_id,
                        "sessionUpdate": "tool_call_update",
                        "status": "completed",
                        "title": "exec",
                        "kind": "other",
                        "content": [{"type": "content", "content": _text_content(message.get("content") or "")}],
                        "rawOutput": output,
                    },
                )
            )
        elif message_type == "ai/failure":
            frames.append(_frame("_posthog/error", {"message": message.get("content") or "Something went wrong"}))
            turn_has_agent_output = True
        else:
            # Kept explicit so the backfill can count what it could not port instead of dropping it.
            frames.append(
                _frame("_posthog/legacy_unmapped", {"legacy_type": message_type, "_meta": {"imported": True}})
            )

    if turn_has_agent_output:
        frames.append(_frame("_posthog/turn_complete", {}))
    return frames


async def _aload_messages(conversation: Conversation, team: Team, user: User) -> list[dict[str, Any]]:
    # Deferred: keeps the LangGraph graph compile off this module's import path; only the mirror pays for it.
    from ee.hogai.api.serializers import aget_conversation_state  # noqa: PLC0415 — keeps LangGraph off the import path
    from ee.hogai.artifacts.manager import ArtifactManager  # noqa: PLC0415 — same
    from ee.hogai.utils.helpers import should_output_assistant_message  # noqa: PLC0415 — same

    state_result = await aget_conversation_state(conversation, team, user)
    if state_result.state is None:
        return []
    enriched = await ArtifactManager(team, user).aenrich_messages(list(state_result.state.messages))
    return [message.model_dump() for message in enriched if should_output_assistant_message(message)]


def _read_copy_progress(run_state: dict[str, Any]) -> CopyProgress:
    return CopyProgress(
        message_count=int(run_state.get(MESSAGES_COPIED_KEY) or 0),
        last_message_id=run_state.get(LAST_MESSAGE_ID_KEY),
    )


def _copy_progress_matches(progress: CopyProgress, messages: list[dict[str, Any]]) -> bool:
    if progress.message_count > len(messages):
        return False
    if progress.message_count == 0 or progress.last_message_id is None:
        return True
    return messages[progress.message_count - 1].get("id") == progress.last_message_id


def _ensure_import_target(
    conversation: Conversation, team: Team, user: User, *, created_at: datetime, updated_at: datetime
) -> tuple[UUID, tasks_contracts.TaskRunDetailDTO]:
    """Find the conversation's task and import run, creating both on first touch."""
    origin_key = origin_key_for_conversation(conversation.id)
    task_id: UUID | None = conversation.task_id
    if task_id is None:
        existing = tasks_facade.get_task_by_origin_key(team.id, origin_key)
        task_id = existing.id if existing is not None else None
    if task_id is None:
        created = tasks_facade.create_imported_task(
            team.id,
            user.id,
            title=conversation.title or "Imported chat",
            origin_key=origin_key,
            internal=bool(conversation.is_internal),
            created_at=created_at,
        )
        task_id = created.id
    # `task__isnull` keeps a concurrent first touch from re-pointing a conversation that already got linked.
    Conversation.objects.filter(id=conversation.id, task__isnull=True).update(task_id=task_id)

    run = tasks_facade.get_imported_task_run(task_id, team.id)
    if run is None:
        run = tasks_facade.create_imported_task_run(
            task_id,
            team.id,
            state={
                "imported_from": IMPORTED_FROM_CONVERSATION,
                "conversation_id": str(conversation.id),
                MESSAGES_COPIED_KEY: 0,
                LAST_MESSAGE_ID_KEY: None,
            },
            created_at=created_at,
            completed_at=updated_at,
        )
    return task_id, run


async def amirror_conversation(conversation_id: UUID | str, team_id: int, user_id: int) -> MirrorResult:
    """Append the conversation's not-yet-mirrored messages to its task-world import run."""
    conversation = await Conversation.objects.aget(id=conversation_id, team_id=team_id)
    if conversation.deleted:
        return MirrorResult(skipped_reason="deleted", task_id=None, run_id=None, appended_frames=0)
    if conversation.type != Conversation.Type.ASSISTANT:
        return MirrorResult(skipped_reason="type", task_id=None, run_id=None, appended_frames=0)
    if conversation.agent_runtime != Conversation.AgentRuntime.LANGGRAPH:
        # Sandbox conversations already are tasks; a converted one continues natively from here on.
        return MirrorResult(skipped_reason="runtime", task_id=None, run_id=None, appended_frames=0)

    team = await Team.objects.aget(id=team_id)
    user = await User.objects.aget(id=user_id)

    messages = await _aload_messages(conversation, team, user)
    if not messages:
        return MirrorResult(skipped_reason="no_messages", task_id=None, run_id=None, appended_frames=0)

    # The model declares these nullable; a persisted conversation always has both.
    updated_at = conversation.updated_at or timezone.now()
    created_at = conversation.created_at or updated_at
    task_id, run = await sync_to_async(_ensure_import_target)(
        conversation, team, user, created_at=created_at, updated_at=updated_at
    )
    progress = _read_copy_progress(run.state)
    if not _copy_progress_matches(progress, messages):
        # The checkpoint history no longer matches what was copied (rewritten or compacted past
        # the copied prefix). The log is append-only, so copying again would duplicate turns; surface it.
        capture_exception(
            RuntimeError("conversation mirror history mismatch"),
            {"conversation_id": str(conversation.id), "task_id": str(task_id), "copied": progress.message_count},
        )
        return MirrorResult(skipped_reason="history_mismatch", task_id=task_id, run_id=run.id, appended_frames=0)

    new_messages = messages[progress.message_count :]
    if not new_messages:
        return MirrorResult(skipped_reason=None, task_id=task_id, run_id=run.id, appended_frames=0)

    frames = project_legacy_messages(new_messages, run_id=str(run.id), include_run_start=progress.message_count == 0)
    appended = await sync_to_async(tasks_facade.append_imported_task_run_log)(
        run.id,
        task_id,
        team_id,
        entries=frames,
        expected_state={MESSAGES_COPIED_KEY: progress.message_count},
        state_updates={MESSAGES_COPIED_KEY: len(messages), LAST_MESSAGE_ID_KEY: messages[-1].get("id")},
        completed_at=updated_at,
    )
    if not appended:
        # The run's copied count is no longer what this copy read: another copy of the same
        # conversation moved it on, and its frames cover ours. Nothing is appended.
        return MirrorResult(skipped_reason="state_mismatch", task_id=task_id, run_id=run.id, appended_frames=0)
    await sync_to_async(tasks_facade.touch_imported_task)(
        task_id, team_id, title=conversation.title, last_activity_at=updated_at
    )
    logger.info(
        "conversation_mirror.appended",
        conversation_id=str(conversation.id),
        task_id=str(task_id),
        run_id=str(run.id),
        frames=len(frames),
        message_count=len(messages),
    )
    return MirrorResult(skipped_reason=None, task_id=task_id, run_id=run.id, appended_frames=len(frames))
