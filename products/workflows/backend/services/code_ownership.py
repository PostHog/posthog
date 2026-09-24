"""Who may write a workflow that a repository owns.

A workflow with `managed_by: code` is defined by a file that one client pushes. Only that client may
change what the workflow is. Every other caller may still operate it and may hand it back to the UI.
The viewset and the serializer both ask `check_write`. Turning a refusal into an HTTP response stays
with them.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final, Optional

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource, get_event_source

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

# An allow-list rather than a deny-list, so an EventSource added upstream is refused by default.
CODE_MANAGED_WRITER_EVENT_SOURCES: Final = frozenset({EventSource.API, EventSource.CLI})

# Matched as whole payloads, so a form body spread into a PATCH cannot release or stop by accident.
_ALLOWED_PAYLOADS: Final = (frozenset({"status"}), frozenset({"managed_by"}))

# Actions that operate a workflow rather than define it, so the file has no opinion on them.
# `schedules` and `schedule_detail` are absent because a schedule is part of the trigger.
_OPERATIONS_ACTIONS: Final = frozenset(
    {
        "rerun",
        "run",
        "invocations",
        "cancel_invocations",
        "batch_jobs",
        "cancel_batch_job",
        "resume_email_sending",
    }
)

_UPDATE_ACTIONS: Final = frozenset({"update", "partial_update"})

# Only these actions carry a workflow as their body. The others carry operations, ids or
# confirmations, so a key in them that shares a workflow field's name is not that field.
_WORKFLOW_BODY_ACTIONS: Final = _UPDATE_ACTIONS | {"create"}

# Keys that fence a write rather than change the row, so they do not make a payload a content edit.
# The editor sends them with every save, including the status-only one.
_INERT_KEYS: Final = frozenset({"base_updated_at", "base_live_updated_at"})

SOURCE_FIELDS: Final = ("source_repository", "source_path", "source_ref")


class RefusalKind(StrEnum):
    MANAGED_BY_CODE = "managed_by_code"
    CLAIM = "claim"
    SOURCE = "source"


@frozen
class OwnershipRefusal:
    kind: RefusalKind
    detail: str
    why: str
    fix: str
    source_repository: Optional[str] = None
    source_path: Optional[str] = None


def is_mcp_transport_request(request: Request) -> bool:
    """Whether this request reached the API through the MCP server."""
    user_agent = request.headers.get("user-agent") or ""
    return request.headers.get("x-posthog-client") == "mcp" or "posthog/mcp-server" in user_agent


def is_code_managed_writer(request: Request) -> bool:
    """Whether this request is the client that pushes the file, and so may write a code-managed row."""
    # `cli` is resolved from client-declared headers, so a browser could claim it from the editor.
    if isinstance(getattr(request, "successful_authenticator", None), SessionAuthentication):
        return False
    # The MCP server forwards a caller-supplied consumer header with no allow-list, so read the
    # transport, which cannot be declared away.
    if is_mcp_transport_request(request):
        return False
    return get_event_source(request) in CODE_MANAGED_WRITER_EVENT_SOURCES


def describe_workflow_source(hog_flow: HogFlow) -> str:
    """Name the file that owns a workflow, as far as the row records it."""
    if hog_flow.source_repository and hog_flow.source_path:
        return f"{hog_flow.source_path} in {hog_flow.source_repository}"
    return hog_flow.source_repository or hog_flow.source_path or "the repository that pushed it"


def _payload_keys(payload: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(payload.keys()) - _INERT_KEYS


def _managed_by_code(hog_flow: HogFlow) -> OwnershipRefusal:
    return OwnershipRefusal(
        kind=RefusalKind.MANAGED_BY_CODE,
        detail=(
            f"This workflow is managed by code, in {describe_workflow_source(hog_flow)}. "
            "Change it there and push, or release it first."
        ),
        why=(
            "A repository is the source of truth for this workflow, so an edit made here would be "
            "reverted by the next push."
        ),
        fix=(
            "Edit the workflow in its file and push it. To hand it back to the UI, send a PATCH whose "
            "only field is managed_by: gui - the next push claims it again."
        ),
        source_repository=hog_flow.source_repository,
        source_path=hog_flow.source_path,
    )


def check_write(
    request: Request, *, action: str, stored: Optional[HogFlow], payload: object
) -> Optional[OwnershipRefusal]:
    """Return why this request may not write `payload` through `action`, or None if it may.

    `stored` is the row the write lands on, None for a create. Pass the row read under the write's
    lock where there is one, because a push can claim the workflow between an earlier read and it.
    `payload` is the raw request body, because validation adds derived fields that would make every
    status-only write look like a content edit.
    """
    if is_code_managed_writer(request):
        return None
    body: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}

    if stored is not None and stored.managed_by == HogFlow.ManagedBy.CODE:
        allowed = action in _OPERATIONS_ACTIONS or (
            action in _UPDATE_ACTIONS and _payload_keys(body) in _ALLOWED_PAYLOADS
        )
        if not allowed:
            return _managed_by_code(stored)

    if action not in _WORKFLOW_BODY_ACTIONS:
        return None

    # A non-writer can never set `code`, so the only ownership change it can make is a release,
    # and the allow-list above already makes a release travel alone.
    if body.get("managed_by") == HogFlow.ManagedBy.CODE:
        return OwnershipRefusal(
            kind=RefusalKind.CLAIM,
            detail="Only a push can mark a workflow as managed by code.",
            why="A workflow managed by code refuses edits from every client except the one that pushes its file.",
            fix="Push the file with the workflows CLI instead.",
        )

    # The source fields are rendered back to the reader: in the refusal, in the badge's tooltip and
    # as a link. A caller that cannot write the row must not put a repository name in front of
    # someone else. Re-sending a stored value passes, because a client that reads a workflow and
    # writes it back sends every field it read.
    for field in SOURCE_FIELDS:
        if field in body and (body[field] or None) != (getattr(stored, field, None) or None):
            return OwnershipRefusal(
                kind=RefusalKind.SOURCE,
                detail=f"Only a push can record where a workflow comes from, so {field} cannot change here.",
                why="The source fields name the file that owns a workflow, and only the client that pushes it knows that.",
                fix=f"Leave {field} out of the request, or send the value the workflow already has.",
            )

    return None
