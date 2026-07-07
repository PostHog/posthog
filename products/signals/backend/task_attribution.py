"""Task attribution for signals API writes, derived from the `X-PostHog-Task-Id` header.

Sandbox agents authenticate with an OAuth token issued on behalf of the task's creator, so
`request.user` alone would mis-attribute agent writes to that human. The sandbox provisioning
bakes the agent's task id into an `X-PostHog-Task-Id` header on its MCP config (and the
agent-server's direct API calls), and the MCP server forwards it — the LLM never handles its own
task id, so attribution is deterministic.

Trust model: the header is caller-supplied attribution metadata, not an authorization boundary —
the bearer token is already team-scoped, and the named task must belong to the same team, so a
caller can only attribute writes to tasks it could already see.
"""

from __future__ import annotations

import uuid

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from products.signals.backend.models import ArtefactAttribution
from products.tasks.backend.facade import api as tasks_api

TASK_ID_HEADER = "X-PostHog-Task-Id"


def resolve_task_id_from_header(request: Request, team_id: int) -> str | None:
    """Return the validated task id from `X-PostHog-Task-Id`, or None when the header is absent.

    Raises a DRF `ValidationError` (→ 400) when the header value is not a UUID, or names a task
    that doesn't exist on this team.
    """
    raw = request.headers.get(TASK_ID_HEADER)
    if not raw or not raw.strip():
        return None
    try:
        task_uuid = uuid.UUID(raw.strip())
    except ValueError:
        raise ValidationError({TASK_ID_HEADER: "must be a task UUID."})
    if not tasks_api.task_exists(task_uuid, team_id):
        raise ValidationError({TASK_ID_HEADER: "unknown task for this project."})
    return str(task_uuid)


def resolve_request_attribution(request: Request, team_id: int) -> ArtefactAttribution:
    """Attribution for an API write: the header task when present, else the requesting user."""
    task_id = resolve_task_id_from_header(request, team_id)
    if task_id is not None:
        return ArtefactAttribution.from_task(task_id)
    user_id = request.user.id
    if user_id is None:  # unreachable behind authentication, but keeps attribution honest
        raise ValidationError("Cannot attribute a write to an anonymous user.")
    return ArtefactAttribution.from_user(user_id)
