"""Pure mapper from LangGraph conversation history to sandbox ACP log frames.

LangGraph conversations persist their turn history as a ``Sequence[AssistantMessageUnion]``
of PostHog schema models (the graph state's ``messages`` channel). Sandbox conversations
persist history as an ACP NDJSON log in S3. This module maps the former onto the latter so a
legacy LangGraph thread can be reopened as a read-only historical sandbox conversation.

The mapper is pure and I/O-free — it takes the validated message list and returns the ordered
list of frame dicts a seeder appends to a synthetic ``TaskRun`` log via ``append_log``. The
conversion is lossy by construction (see the migration plan's lossiness contract): human and
plain-assistant turns convert faithfully; tool-call cards degrade to name+input / output-text
without live status, server attribution, or ``_meta``; visualization and notebook artifacts
degrade to text. ``ContextMessage`` and internal messages are dropped.

Frames are emitted as the non-chunk forms the frontend ingests: ``_posthog/user_message`` for
the user turn and ``session/update`` (``agent_message`` / ``tool_call`` / ``tool_call_update``)
for assistant output. ``agent_message_chunk`` is NEVER emitted — ``append_log`` strips chunk
frames, so a chunk would silently vanish.
"""

import json
from collections.abc import Sequence
from typing import Any

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    ContextMessage,
    FailureMessage,
    HumanMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    PlanningMessage,
    ReasoningMessage,
    TaskExecutionMessage,
    VisualizationMessage,
)

from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantMessageUnion

# Wire-method constants — mirror products/posthog_ai/backend/wire_types.py and the frontend's
# sandboxWireTypes.ts. The frontend's `isNotificationFrame` requires `type: "notification"` on
# the envelope, so every emitted frame carries it (the live agent-server stamps it too).
METHOD_USER_MESSAGE = "_posthog/user_message"
METHOD_SESSION_UPDATE = "session/update"


def messages_to_acp_frames(messages: Sequence[AssistantMessageUnion]) -> list[dict[str, Any]]:
    """Map LangGraph ``state.messages`` onto an ordered list of ACP log frames.

    Pure and I/O-free. Emits one or more frames per source message per the migration plan's
    mapping table; ``ContextMessage`` and unrenderable internal messages produce no frames.
    Never emits ``agent_message_chunk`` (it would be stripped by ``append_log``).
    """
    frames: list[dict[str, Any]] = []
    for message in messages:
        frames.extend(_map_message(message))
    return frames


def _map_message(message: AssistantMessageUnion) -> list[dict[str, Any]]:
    if isinstance(message, HumanMessage):
        return _map_human_message(message)
    if isinstance(message, AssistantMessage):
        return _map_assistant_message(message)
    if isinstance(message, AssistantToolCallMessage):
        return _map_tool_call_message(message)
    if isinstance(message, VisualizationMessage):
        return _map_visualization_message(message)
    if isinstance(message, MultiVisualizationMessage):
        return _map_multi_visualization_message(message)
    if isinstance(message, NotebookUpdateMessage):
        return _map_notebook_message(message)
    if isinstance(message, FailureMessage):
        return _map_failure_message(message)
    if isinstance(message, ReasoningMessage):
        return _map_reasoning_message(message)
    if isinstance(message, (PlanningMessage, TaskExecutionMessage, ArtifactRefMessage, ContextMessage)):
        # ContextMessage is never surfaced to users (filtered today by
        # should_output_assistant_message); planning/task-execution/artifact-ref are
        # transient internal step messages with no standalone ACP card — dropped.
        return []
    return []


def _map_human_message(message: HumanMessage) -> list[dict[str, Any]]:
    """Human turn → ``_posthog/user_message`` — the same shape ``_log_user_message`` writes."""
    return [_user_message_frame(message.content)]


def _map_assistant_message(message: AssistantMessage) -> list[dict[str, Any]]:
    """Plain assistant text → ``agent_message``; any ``tool_calls`` → one ``tool_call`` each.

    An assistant message can carry both prose and tool calls; emit the text frame first (when
    present) so the rendered order matches the source turn, then a ``tool_call`` per call.
    """
    frames: list[dict[str, Any]] = []
    if message.content:
        frames.append(_agent_message_frame(message.id, message.content))
    for tool_call in message.tool_calls or []:
        frames.append(_tool_call_frame(tool_call))
    return frames


def _map_tool_call_message(message: AssistantToolCallMessage) -> list[dict[str, Any]]:
    """Tool result → ``tool_call_update`` with ``status: completed`` and the output text.

    ``ui_payload`` (the contextual-tool frontend payload) has no ACP equivalent and is dropped.
    """
    return [_tool_call_update_frame(message.tool_call_id, message.content)]


def _map_visualization_message(message: VisualizationMessage) -> list[dict[str, Any]]:
    """Visualization card → degraded ``tool_call_update`` carrying the serialized query/answer.

    The LangGraph insight-preview card does not round-trip to the sandbox visualization
    extractor; degrade to a JSON/text block under ``rawOutput`` keyed off the message id.
    """
    payload: dict[str, Any] = {"answer": _model_to_jsonable(message.answer)}
    if message.plan:
        payload["plan"] = message.plan
    if message.query:
        payload["query"] = message.query
    return [_tool_call_update_frame(_synthetic_tool_call_id(message.id, "viz"), json.dumps(payload))]


def _map_multi_visualization_message(message: MultiVisualizationMessage) -> list[dict[str, Any]]:
    """Multi-visualization card → degraded ``tool_call_update`` with the visualizations serialized."""
    payload: dict[str, Any] = {
        "visualizations": [_model_to_jsonable(item) for item in message.visualizations],
    }
    if message.commentary:
        payload["commentary"] = message.commentary
    return [_tool_call_update_frame(_synthetic_tool_call_id(message.id, "multiviz"), json.dumps(payload))]


def _map_notebook_message(message: NotebookUpdateMessage) -> list[dict[str, Any]]:
    """Notebook artifact → text summary ``agent_message``; the live notebook artifact is gone."""
    summary = f"Notebook {message.notebook_id} ({message.notebook_type})."
    return [_agent_message_frame(message.id, summary)]


def _map_failure_message(message: FailureMessage) -> list[dict[str, Any]]:
    """Failure → ``agent_message`` carrying the failure text (or a generic fallback)."""
    content = message.content or "The assistant encountered an error."
    return [_agent_message_frame(message.id, content)]


def _map_reasoning_message(message: ReasoningMessage) -> list[dict[str, Any]]:
    """Reasoning step → ``agent_message`` with the reasoning text (best-effort, no live thinking UI)."""
    if not message.content:
        return []
    return [_agent_message_frame(message.id, message.content)]


def _user_message_frame(content: str) -> dict[str, Any]:
    return {
        "type": "notification",
        "notification": {
            "method": METHOD_USER_MESSAGE,
            "params": {"content": content},
        },
    }


def _agent_message_frame(message_id: str | None, text: str) -> dict[str, Any]:
    update: dict[str, Any] = {"sessionUpdate": "agent_message", "content": {"text": text}}
    if message_id:
        update["messageId"] = message_id
    return _session_update_frame(update)


def _tool_call_frame(tool_call: AssistantToolCall) -> dict[str, Any]:
    update: dict[str, Any] = {
        "sessionUpdate": "tool_call",
        "toolCallId": tool_call.id,
        "toolName": tool_call.name,
        "input": tool_call.args,
        "status": "completed",
    }
    return _session_update_frame(update)


def _tool_call_update_frame(tool_call_id: str, raw_output: str) -> dict[str, Any]:
    update: dict[str, Any] = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": tool_call_id,
        "status": "completed",
        "rawOutput": raw_output,
    }
    return _session_update_frame(update)


def _session_update_frame(update: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "notification",
        "notification": {
            "method": METHOD_SESSION_UPDATE,
            "params": {"update": update},
        },
    }


def _synthetic_tool_call_id(message_id: str | None, prefix: str) -> str:
    """Stable synthetic id for cards that have no source tool-call id (visualizations).

    The frontend keys tool invocations by ``toolCallId``; a missing id makes the update a no-op.
    Derive a deterministic id from the message id so repeated conversions stay stable.
    """
    return f"{prefix}_{message_id}" if message_id else f"{prefix}_unknown"


def _model_to_jsonable(value: Any) -> Any:
    """Serialize a pydantic schema model (or plain value) to a JSON-able structure."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    return value
