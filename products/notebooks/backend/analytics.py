"""Analytics capture for notebook lifecycle events.

Single owner of the server-side `notebook created` event so every creation path — REST/MCP
(via the serializer) and the AI/background paths (via the facade create functions) — emits one
uniform event with an attributed `creation_source`.
"""

from typing import TYPE_CHECKING, Any

from posthog.event_usage import report_user_action, report_user_or_team_action
from posthog.models import Team, User

if TYPE_CHECKING:
    from rest_framework.request import Request

NOTEBOOK_CREATED_EVENT = "notebook created"


class NotebookCreationSource:
    UI = "ui"
    MCP = "mcp"
    MAX_AI = "max_ai"
    MAX_ACCOUNT_NOTEBOOK = "max_account_notebook"
    TEMPORAL_AGENT = "temporal_agent"
    GROUP_AUTO = "group_auto"
    # Neutral default for the generic facade create; real callers pass their own source.
    SERVER = "server"


def notebook_node_count(content: Any) -> int | None:
    """Top-level node count of a ProseMirror `{type: doc, content: [...]}` document."""
    if isinstance(content, dict):
        nodes = content.get("content")
        return len(nodes) if isinstance(nodes, list) else 0
    return None


def _created_properties(short_id: str, creation_source: str, extra: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {"short_id": short_id, "creation_source": creation_source}
    props.update({key: value for key, value in extra.items() if value is not None})
    return props


def capture_notebook_created(
    *,
    short_id: str,
    creation_source: str,
    team_id: int,
    user: User | None = None,
    created_by_id: int | None = None,
    request: "Request | None" = None,
    mcp_client: str | None = None,
    api_key_type: str | None = None,
    conversation_id: str | None = None,
    topic: str | None = None,
    visibility: str | None = None,
    node_count: int | None = None,
) -> None:
    """Emit `notebook created`. Pass ``request`` + ``user`` from the DRF serializer (REST/MCP);
    the facade create functions pass ``team_id`` + ``created_by_id`` for the request-less
    AI/background paths, where attribution falls back to the team when there is no user
    (e.g. group auto-create)."""
    props = _created_properties(
        short_id,
        creation_source,
        {
            "mcp_client": mcp_client,
            "api_key_type": api_key_type,
            "conversation_id": conversation_id,
            "topic": topic,
            "visibility": visibility,
            "node_count": node_count,
        },
    )

    if request is not None and user is not None:
        report_user_action(user, NOTEBOOK_CREATED_EVENT, props, request=request)
        return

    resolved_user = user
    if resolved_user is None and created_by_id is not None:
        resolved_user = User.objects.filter(pk=created_by_id).first()
    team = Team.objects.filter(pk=team_id).first()
    if team is None:
        return
    report_user_or_team_action(NOTEBOOK_CREATED_EVENT, props, user=resolved_user, team=team)
