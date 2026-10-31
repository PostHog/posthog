"""Actor attribution for signals API writes.

Sandbox agents authenticate with an OAuth token issued on behalf of the task's creator, so
`request.user` alone would mis-attribute agent writes to that human. The sandbox provisioning
bakes the agent's task id into an `X-PostHog-Task-Id` header on its MCP config and direct API
calls. The MCP server forwards it, so the LLM never handles its own task id and attribution is
deterministic.

External MCP agents do not have an internal task. The MCP server forwards their effective client
name, which is stored together with the authenticated user principal.

Trust model: the header is caller-supplied attribution metadata, not an authorization boundary.
The bearer token is already team-scoped, and the named task must belong to the same team, so a
caller can only attribute writes to tasks it could already see.
"""

from __future__ import annotations

import uuid

from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.oauth_provenance import get_oauth_access_token

from products.signals.backend.models import ArtefactAttribution
from products.tasks.backend.facade import api as tasks_api

TASK_ID_HEADER = "X-PostHog-Task-Id"
MCP_CLIENT_NAME_HEADER = "X-Posthog-Mcp-Client-Name"
MCP_CLIENT_HEADER = "X-PostHog-Client"
MAX_AGENT_NAME_LENGTH = 200
SCOUT_TASK_ORIGIN = "signals_scout"
# Pipeline research and implementation runs, and the Discuss and Create PR runs a person starts
# from the inbox, all share this origin. Only the pipeline ones are internal.
REPORT_TASK_ORIGIN = "signal_report"


def resolve_task_id_from_header(request: Request, team_id: int) -> str | None:
    """Return the validated task id from `X-PostHog-Task-Id`, or None when the header is absent.

    Raises a DRF `ValidationError` with a 400 response when the header value is not a UUID, or names a task
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
    """Resolve the internal task, external MCP agent, or requesting user for an API write."""
    task_id = resolve_task_id_from_header(request, team_id)
    if task_id is not None:
        return ArtefactAttribution.from_task(task_id)
    user_id = request.user.id
    if user_id is None:  # unreachable behind authentication, but keeps attribution honest
        raise ValidationError("Cannot attribute a write to an anonymous user.")
    agent_name = resolve_external_agent_name(request)
    if agent_name is not None:
        return ArtefactAttribution.from_agent(user_id, agent_name)
    return ArtefactAttribution.from_user(user_id)


def resolve_external_agent_name(request: Request) -> str | None:
    """Return the MCP client identity forwarded by the gateway, when this is an MCP request."""
    raw = request.headers.get(MCP_CLIENT_NAME_HEADER)
    if not raw and request.headers.get(MCP_CLIENT_HEADER, "").strip().lower() == "mcp":
        raw = "mcp"
    value = raw.strip() if raw else ""
    return value[:MAX_AGENT_NAME_LENGTH] or None


def is_token_bound_task(request: Request, attribution: ArtefactAttribution) -> bool:
    """Whether the OAuth token was issued for the task this request attributes its writes to.

    The header is caller-supplied metadata, so it carries no authority on its own. A decision that
    turns on which agent is calling needs this check; plain attribution does not.
    """
    if attribution.task_id is None:
        return False
    bound_task_id = getattr(get_oauth_access_token(request), "sandbox_task_id", None)
    return bound_task_id is not None and str(bound_task_id) == attribution.task_id


def is_automatic_signal_agent(request: Request, attribution: ArtefactAttribution, team_id: int) -> bool:
    """Whether a pipeline or scout task makes this request.

    A run a person starts from the inbox answers for that person, so it is not automatic even
    though it shares the report origin with the pipeline. The pipeline creates its tasks internal,
    which is what separates the two.
    """
    if not is_token_bound_task(request, attribution):
        return False
    tasks = tasks_api.get_tasks_by_ids([attribution.task_id], [team_id]) if attribution.task_id else []
    if not tasks:
        return False
    task = tasks[0]
    return task.origin_product == SCOUT_TASK_ORIGIN or (task.origin_product == REPORT_TASK_ORIGIN and task.internal)
