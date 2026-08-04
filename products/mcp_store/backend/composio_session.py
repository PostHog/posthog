"""Resolving the tool-router session that serves a user's connected apps.

Split from `composio.py` so the API client stays free of model imports. This is the layer that
knows a session must cover exactly the toolkits a user has connected, and rebuilds it when that
set changes.
"""

from __future__ import annotations

from django.conf import settings

import structlog

from .composio import ComposioError, composio_enabled, composio_user_id, create_session, session_config_fingerprint
from .models import MCPComposioConnection, MCPComposioSession, MCPServerInstallation

logger = structlog.get_logger(__name__)


def composio_redirect_uri() -> str:
    return f"{settings.SITE_URL}/api/mcp_store/composio_redirect/"


# Every query here scopes explicitly with `for_team` rather than relying on ambient context.
# These run from Temporal activities and the gateway proxy as well as from request handlers, and
# the fail-closed managers raise rather than silently returning nothing when no context is set.


def connected_toolkit_slugs(installation: MCPServerInstallation) -> list[str]:
    return sorted(
        MCPComposioConnection.objects.for_team(installation.team_id)
        .filter(installation=installation, status="active")
        .values_list("toolkit_slug", flat=True)
    )


def invalidate_session(installation: MCPServerInstallation) -> None:
    """Mark the stored session stale without deleting it.

    Blanking the fingerprint rather than dropping the row keeps the old session usable right up
    until the next resolve rebuilds it, so a connect never briefly breaks an in-flight agent run.
    """
    MCPComposioSession.objects.for_team(installation.team_id).filter(installation=installation).update(
        config_fingerprint=""
    )


def resolve_session_url(installation: MCPServerInstallation) -> str | None:
    """The MCP endpoint for this user's connected apps, rebuilding the session if it's stale.

    Returns None when there is nothing to serve (Composio off, or no connected app), which callers
    treat as "this user has no Composio server" rather than as an error.
    """
    if not composio_enabled():
        return None

    toolkits = connected_toolkit_slugs(installation)
    if not toolkits:
        return None

    fingerprint = session_config_fingerprint(toolkits)
    session = MCPComposioSession.objects.for_team(installation.team_id).filter(installation=installation).first()
    if session is not None and session.config_fingerprint == fingerprint and session.mcp_url:
        return session.mcp_url

    try:
        info = create_session(
            user_id=composio_user_id(installation.team_id, installation.user_id),
            toolkit_slugs=toolkits,
            callback_url=composio_redirect_uri(),
            team_id=installation.team_id,
        )
    except ComposioError:
        logger.exception("Composio session resolve failed", installation_id=str(installation.id))
        # Fall back to a stale session rather than dropping the user's tools entirely: it still
        # serves every toolkit connected before the one that failed to take effect.
        return session.mcp_url if session is not None and session.mcp_url else None

    MCPComposioSession.objects.for_team(installation.team_id).update_or_create(
        installation=installation,
        defaults={
            "team_id": installation.team_id,
            "session_id": info.session_id,
            "mcp_url": info.mcp_url,
            "config_version": info.config_version,
            "config_fingerprint": fingerprint,
        },
    )
    return info.mcp_url


def has_connected_apps(installation: MCPServerInstallation) -> bool:
    return (
        MCPComposioConnection.objects.for_team(installation.team_id)
        .filter(installation=installation, status="active")
        .exists()
    )
