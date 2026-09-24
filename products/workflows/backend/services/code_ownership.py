from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final, Optional

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource, get_event_source

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

CODE_MANAGED_WRITER_EVENT_SOURCES: Final = frozenset({EventSource.API, EventSource.CLI})

_ALLOWED_PAYLOADS: Final = (frozenset({"status"}), frozenset({"managed_by"}))

_OPERATIONS_ACTIONS: Final = frozenset(
    {
        "rerun",
        "run",
        "invocations",
        "cancel_invocations",
        "batch_jobs",
        "cancel_batch_job",
        "resume_email_sending",
        "schedules",
        "schedule_detail",
    }
)

_UPDATE_ACTIONS: Final = frozenset({"update", "partial_update"})

_WORKFLOW_BODY_ACTIONS: Final = _UPDATE_ACTIONS | {"create"}

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
    user_agent = request.headers.get("user-agent") or ""
    return request.headers.get("x-posthog-client") == "mcp" or "posthog/mcp-server" in user_agent


def is_code_managed_writer(request: Request) -> bool:
    if isinstance(getattr(request, "successful_authenticator", None), SessionAuthentication):
        return False
    if is_mcp_transport_request(request):
        return False
    return get_event_source(request) in CODE_MANAGED_WRITER_EVENT_SOURCES


def describe_workflow_source(hog_flow: HogFlow) -> str:
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

    if body.get("managed_by") == HogFlow.ManagedBy.CODE:
        return OwnershipRefusal(
            kind=RefusalKind.CLAIM,
            detail="Only a push can mark a workflow as managed by code.",
            why="A workflow managed by code refuses edits from every client except the one that pushes its file.",
            fix="Push the file with the workflows CLI instead.",
        )

    for field in SOURCE_FIELDS:
        if field in body and (body[field] or None) != (getattr(stored, field, None) or None):
            return OwnershipRefusal(
                kind=RefusalKind.SOURCE,
                detail=f"Only a push can record where a workflow comes from, so {field} cannot change here.",
                why="The source fields name the file that owns a workflow, and only the client that pushes it knows that.",
                fix=f"Leave {field} out of the request, or send the value the workflow already has.",
            )

    return None
