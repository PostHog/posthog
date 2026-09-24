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

from posthog.schema import ContextMessage

from posthog.dataclasses import frozen
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
_EXEC_TOOL_NAME = "mcp__posthog__exec"

# The task thread keys its widgets (insight card, SQL result, recordings list) on the exec sub-tool
# names; a legacy tool call is written under the sub-tool name so the same widget renders it.
_EXEC_SUB_TOOL_BY_LEGACY_NAME = {
    "create_insight": "insight-create",
    "execute_sql": "execute-sql",
    "search_session_recordings": "query-session-recordings-list",
    "filter_session_recordings": "query-session-recordings-list",
}


def _tool_meta(tool_call_id: str, **claude_code: Any) -> dict[str, Any]:
    # The sandbox resume parser rebuilds tool history only from _meta.claudeCode, not the ACP top-level fields.
    return {"claudeCode": {"toolName": _EXEC_TOOL_NAME, "toolCallId": tool_call_id, **claude_code}, "imported": True}


@frozen
class CopyProgress:
    message_count: int
    last_message_id: str | None


class CopyConflict(Exception):
    """Another copy of the same conversation moved the run on first; the caller retries."""


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


def _text_content(text: str) -> dict[str, Any]:
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
        if message_type in ("human", "context"):
            if turn_has_agent_output:
                frames.append(_frame("_posthog/turn_complete", {}))
                turn_has_agent_output = False
            content = _text_content(message.get("content") or "")
            if message_type == "context":
                # LangGraph sends context messages (compaction summary, mode notes) to the model as user
                # turns nobody typed. The hidden marker keeps them out of the thread and in the resumed history.
                content["_meta"] = {"ui": {"hidden": True}}
            frames.append(
                _session_update(
                    session_id,
                    {
                        "sessionUpdate": "user_message_chunk",
                        "content": content,
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
                sub_tool = _EXEC_SUB_TOOL_BY_LEGACY_NAME.get(tool_call["name"], tool_call["name"])
                command = f"call {sub_tool} {json.dumps(args)}"
                base = {
                    "_meta": _tool_meta(tool_call["id"], toolInput={"command": command}),
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
                        "_meta": _tool_meta(tool_call_id, toolResponse=output),
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


async def _aload_messages(conversation: Conversation, team: Team, user: User) -> list[dict[str, Any]] | None:
    """The conversation's completed turns, or None when the checkpoint holds content this copy cannot read.

    A read error raises so the activity retries; unsupported content does not change on retry.
    """
    # Deferred: keeps the LangGraph graph compile off this module's import path; only the mirror pays for it.
    from ee.hogai.api.serializers import aget_conversation_state  # noqa: PLC0415 — keeps LangGraph off the import path
    from ee.hogai.artifacts.manager import ArtifactManager  # noqa: PLC0415 — same
    from ee.hogai.utils.helpers import should_output_assistant_message  # noqa: PLC0415 — same

    state_result = await aget_conversation_state(conversation, team, user, raise_on_error=True)
    if state_result.has_unsupported_content:
        return None
    if state_result.state is None:
        return []
    enriched = await ArtifactManager(team, user).aenrich_messages(list(state_result.state.messages))
    # Context messages are model-only; the thread never shows them, but the resumed agent needs them.
    messages = [
        # JSON mode: the frames are written as JSON lines, and a plain Enum member cannot encode.
        message.model_dump(mode="json")
        for message in enriched
        if isinstance(message, ContextMessage) or should_output_assistant_message(message)
    ]
    return _completed_turns(messages)


def _completed_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a trailing turn that is still in progress.

    A turn is complete once the assistant gave its final answer or failed. A trailing tool call
    without its result, or an approval the user has not answered yet, is copied by the next run,
    after the turn has ended.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("type") == "ai/failure" or (message.get("type") == "ai" and not message.get("tool_calls")):
            return messages[: index + 1]
    return []


def _read_copy_progress(run_state: dict[str, Any]) -> CopyProgress:
    return CopyProgress(
        message_count=int(run_state.get(MESSAGES_COPIED_KEY) or 0),
        last_message_id=run_state.get(LAST_MESSAGE_ID_KEY),
    )


def _uncopied_messages(progress: CopyProgress, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages after the last copied one.

    The anchor is the last copied message's id, not its position: LangGraph compaction replaces
    the stored list with a shorter window, so positions move. An anchor still in the list means
    everything after it is new. An anchor that is gone means the window starts after it, so
    everything in the list is new.
    """
    if progress.last_message_id is None:
        return messages
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("id") == progress.last_message_id:
            return messages[index + 1 :]
    return messages


def _ensure_import_target(
    conversation: Conversation, team: Team, user: User, *, created_at: datetime, updated_at: datetime
) -> tuple[UUID, tasks_contracts.TaskRunDetailDTO] | None:
    """Find the conversation's task and import run, creating both on first touch.

    Returns None when the conversation's task was deleted: the chat has no task-world copy anymore.
    """
    origin_key = origin_key_for_conversation(conversation.id)
    existing = tasks_facade.get_task_by_origin_key(team.id, origin_key)
    if conversation.task_id is not None and existing is None:
        return None
    task_id: UUID | None = existing.id if existing is not None else None
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
    if conversation.is_internal:
        # A support agent made this chat while impersonating the customer, who must never see it; a task would be theirs.
        return MirrorResult(skipped_reason="internal", task_id=None, run_id=None, appended_frames=0)
    if conversation.type != Conversation.Type.ASSISTANT:
        return MirrorResult(skipped_reason="type", task_id=None, run_id=None, appended_frames=0)
    if conversation.agent_runtime != Conversation.AgentRuntime.LANGGRAPH:
        # Sandbox conversations already are tasks; a converted one continues natively from here on.
        return MirrorResult(skipped_reason="runtime", task_id=None, run_id=None, appended_frames=0)
    if conversation.user_id != user_id:
        # The copy runs as the chat's owner: only the owner can send it messages, and the task is theirs.
        return MirrorResult(skipped_reason="owner_mismatch", task_id=None, run_id=None, appended_frames=0)

    team = await Team.objects.aget(id=team_id)
    user = await User.objects.aget(id=user_id)

    messages = await _aload_messages(conversation, team, user)
    if messages is None:
        return MirrorResult(skipped_reason="unsupported_content", task_id=None, run_id=None, appended_frames=0)
    if not messages:
        return MirrorResult(skipped_reason="no_messages", task_id=None, run_id=None, appended_frames=0)

    # The model declares these nullable; a persisted conversation always has both.
    updated_at = conversation.updated_at or timezone.now()
    created_at = conversation.created_at or updated_at
    target = await sync_to_async(_ensure_import_target)(
        conversation, team, user, created_at=created_at, updated_at=updated_at
    )
    if target is None:
        return MirrorResult(skipped_reason="task_deleted", task_id=None, run_id=None, appended_frames=0)
    task_id, run = target
    progress = _read_copy_progress(run.state)
    new_messages = _uncopied_messages(progress, messages)
    if not new_messages:
        return MirrorResult(skipped_reason=None, task_id=task_id, run_id=run.id, appended_frames=0)

    frames = project_legacy_messages(
        new_messages, run_id=str(run.id), include_run_start=progress.last_message_id is None
    )
    appended = await sync_to_async(tasks_facade.append_imported_task_run_log)(
        run.id,
        task_id,
        team_id,
        entries=frames,
        batch_id=f"after:{progress.message_count}",
        expected_state={MESSAGES_COPIED_KEY: progress.message_count},
        state_updates={
            MESSAGES_COPIED_KEY: progress.message_count + len(new_messages),
            LAST_MESSAGE_ID_KEY: new_messages[-1].get("id"),
        },
        completed_at=updated_at,
    )
    if not appended:
        # The run's copied count is no longer what this copy read: another copy of the same
        # conversation moved it on. It may have copied fewer turns than this one saw, so the retry
        # re-reads the run and appends whatever is still missing.
        raise CopyConflict(f"conversation {conversation.id}: copied count moved past {progress.message_count}")
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
