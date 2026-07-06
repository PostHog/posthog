"""Typed views of the slice of the sandbox agent wire format the Python backend consumes.

The backend only ever reads persisted log entries (S3 NDJSON replayed via the products/tasks
``logs/`` path) — today to walk prior ``_posthog/user_message`` notifications for context
dedup on follow-ups. Live SSE frames are consumed exclusively by the frontend, where the full
contract is typed at ``products/posthog_ai/frontend/sandbox/types/sandboxWireTypes.ts``; keep that copy in
mind when extending this one.

The envelope is validated with tolerant pydantic models (we co-own its shape with
products/tasks); ``notification.params`` is owned by the external agent adapters, so it is
typed via TypedDict + TypeGuard and never runtime-validated outside tests — old S3 log entries
replay forever, and a parse path that raises on a historical or future shape would break
conversation loads.
"""

from typing import Any, Literal, NotRequired, TypedDict, TypeGuard

from pydantic import BaseModel, ConfigDict, ValidationError


class AcpError(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: int | None = None
    message: str | None = None


class AcpNotificationBody(BaseModel):
    """JSON-RPC notification carried inside a ``notification`` log entry."""

    model_config = ConfigDict(extra="allow")

    jsonrpc: str | None = None
    method: str | None = None
    # Adapter-owned; narrow with the TypeGuards below instead of validating here.
    params: Any = None
    result: Any = None
    error: AcpError | None = None


class NotificationFrame(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["notification"]
    timestamp: str | None = None
    notification: AcpNotificationBody


class UnknownFrame(BaseModel):
    """Fallback for entries this module doesn't recognize. Carries the raw payload untouched."""

    raw: dict[str, Any]


def parse_log_entry(data: dict[str, Any]) -> NotificationFrame | UnknownFrame:
    """Classify a raw persisted log entry. Never raises — unknown or malformed entries come
    back as ``UnknownFrame`` so a single bad entry can't abort a log walk."""
    if data.get("type") != "notification":
        return UnknownFrame(raw=data)
    try:
        return NotificationFrame.model_validate(data)
    except ValidationError:
        return UnknownFrame(raw=data)


METHOD_USER_MESSAGE = "_posthog/user_message"


class UserMessageParams(TypedDict):
    """Params of a ``_posthog/user_message`` notification — the user's message as the
    agent-server echoed it into the log (plain string or ACP content blocks)."""

    content: NotRequired[str | list[dict[str, Any]]]
    # Carries `attached_context` — the full undeduped context recorded with the message.
    _meta: NotRequired[dict[str, Any]]


def is_user_message_params(params: object, method: str | None) -> TypeGuard[UserMessageParams]:
    return method == METHOD_USER_MESSAGE and isinstance(params, dict)
