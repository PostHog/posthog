"""Analytics capture for notebook lifecycle events.

Single owner of the server-side `notebook created` and `notebook read` events, so every
creation path (REST/MCP via the serializer, AI/background via the facade create functions) and
every programmatic read emits one uniform, attributed event.
"""

from typing import TYPE_CHECKING, Any

from posthog.event_usage import report_user_action, report_user_or_team_action
from posthog.models import Team, User

if TYPE_CHECKING:
    from rest_framework.request import Request

NOTEBOOK_CREATED_EVENT = "notebook created"
NOTEBOOK_READ_EVENT = "notebook read"


class NotebookCreationSource:
    UI = "ui"
    MCP = "mcp"
    MAX_AI = "max_ai"
    TEMPORAL_AGENT = "temporal_agent"
    GROUP = "group"
    # Neutral default for the generic facade create; real callers pass their own source.
    SERVER = "server"
    # The account-notebook path (max_account_notebook) is deferred; its source lands with it.


def notebook_node_count(content: Any) -> int | None:
    """Top-level node count of a ProseMirror `{type: doc, content: [...]}` document."""
    if isinstance(content, dict):
        nodes = content.get("content")
        return len(nodes) if isinstance(nodes, list) else 0
    return None


def _optional_props(**props: Any) -> dict[str, Any]:
    """Keep only the props whose value is not None, so optional event fields don't clutter the payload."""
    return {key: value for key, value in props.items() if value is not None}


def capture_notebook_created(
    *,
    short_id: str,
    creation_source: str,
    team_id: int,
    user: User | None = None,
    created_by_id: int | None = None,
    request: "Request | None" = None,
    mcp_consumer: str | None = None,
    mcp_oauth_client: str | None = None,
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
    props = {
        "short_id": short_id,
        "creation_source": creation_source,
        **_optional_props(
            mcp_consumer=mcp_consumer,
            mcp_oauth_client=mcp_oauth_client,
            api_key_type=api_key_type,
            conversation_id=conversation_id,
            topic=topic,
            visibility=visibility,
            node_count=node_count,
        ),
    }

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


def capture_notebook_read(
    *,
    request: "Request",
    user: Any,
    short_id: str,
    read_source: str,
    is_creator: bool,
    user_access_level: str | None = None,
    mcp_consumer: str | None = None,
    mcp_oauth_client: str | None = None,
    api_key_type: str | None = None,
) -> None:
    """Emit `notebook read` for a programmatic (non-browser) notebook retrieve. Browser opens are
    the client-side `notebook opened` event, so the caller gates this on non-session auth to keep
    agent traffic out of the human revisit numbers."""
    props = {
        "short_id": short_id,
        "read_source": read_source,
        "is_creator": is_creator,
        **_optional_props(
            user_access_level=user_access_level,
            mcp_consumer=mcp_consumer,
            mcp_oauth_client=mcp_oauth_client,
            api_key_type=api_key_type,
        ),
    }
    report_user_action(user, NOTEBOOK_READ_EVENT, props, request=request)
