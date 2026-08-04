"""Composio: managed auth and tools for the long tail of apps the direct catalog can't reach.

Composio serves every connected toolkit through **one** tool-router session per user, so a user's
whole Composio estate is a single `MCPServerInstallation` with an `MCPComposioConnection` per
toolkit. Two consequences shape everything here:

- The session's MCP endpoint authenticates with our instance-wide `COMPOSIO_API_KEY`, so the URL
  must never leave the server. Agents reach it through the gateway proxy, which holds the key.
- The session exposes meta-tools (`COMPOSIO_MULTI_EXECUTE_TOOL`, `COMPOSIO_SEARCH_TOOLS`, ...)
  rather than a flat tool list, so the real tool slug lives *inside* an execute call's arguments.
  Anything enforcing or auditing per-tool policy has to unwrap it — see `composio_executed_tools`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import structlog

from posthog.egress.composio.transport import composio_request, is_composio_configured
from posthog.egress.limiter.policies import Priority

logger = structlog.get_logger(__name__)

SESSION_PATH = "/api/v3.1/tool_router/session"
AUTH_CONFIGS_PATH = "/api/v3/auth_configs"
CONNECTED_ACCOUNTS_LINK_PATH = "/api/v3/connected_accounts/link"
TOOLKITS_PATH = "/api/v3/toolkits"

EGRESS_SOURCE = "mcp_store"

# The single installation every Composio toolkit is served through. Users never see this as a
# server; they see the apps they connected. It exists because one tool-router session covers a
# user's whole estate, so there is exactly one credential and one gateway registration.
COMPOSIO_HUB_URL = "https://composio.dev/"
COMPOSIO_HUB_NAME = "Connected apps"

# The meta-tool the router exposes for running a real tool. Its arguments carry the actual slug.
EXECUTE_TOOL_NAMES = frozenset({"COMPOSIO_MULTI_EXECUTE_TOOL", "COMPOSIO_EXECUTE_TOOL"})


class ComposioError(Exception):
    pass


@dataclass(frozen=True)
class ConnectionLink:
    redirect_url: str
    connected_account_id: str


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    mcp_url: str
    config_version: int


@dataclass(frozen=True, kw_only=True)
class ToolkitInfo:
    slug: str
    name: str
    description: str
    categories: tuple[str, ...]
    tools_count: int
    app_url: str


def composio_user_id(team_id: int, user_id: int) -> str:
    """The identity Composio keys connected accounts on.

    Scoped by team as well as user so one person's connections don't bleed across the projects
    they belong to — it mirrors `MCPServerInstallation` being unique per (team, user, url). No
    email or name: Composio only ever needs an opaque stable handle.
    """
    return f"posthog:{team_id}:{user_id}"


def _json(response: Any, *, context: str) -> dict[str, Any]:
    if response.status_code >= 400:
        logger.warning("Composio API error", context=context, status=response.status_code, body=response.text[:500])
        raise ComposioError(f"Composio {context} failed with {response.status_code}")
    try:
        return response.json()
    except ValueError as e:
        raise ComposioError(f"Composio {context} returned a non-JSON body") from e


def list_managed_toolkits() -> list[ToolkitInfo]:
    """Every toolkit Composio can authenticate with its own OAuth apps.

    That subset is the whole point of the integration: it needs no per-vendor OAuth app from us,
    so it's installable the moment it appears. Toolkits requiring our own credentials are skipped
    until we decide to register apps for them.
    """
    toolkits: list[ToolkitInfo] = []
    cursor: str | None = None
    while True:
        path = f"{TOOLKITS_PATH}?limit=200" + (f"&cursor={cursor}" if cursor else "")
        payload = _json(
            composio_request("GET", path, source=EGRESS_SOURCE, priority=Priority.BATCH),
            context="toolkit listing",
        )
        for item in payload.get("items") or []:
            if not item.get("composio_managed_auth_schemes"):
                continue
            meta = item.get("meta") or {}
            toolkits.append(
                ToolkitInfo(
                    slug=item.get("slug") or "",
                    name=item.get("name") or "",
                    description=(meta.get("description") or "").strip(),
                    categories=tuple(c.get("name", "") for c in meta.get("categories") or []),
                    tools_count=int(meta.get("tools_count") or 0),
                    app_url=meta.get("app_url") or "",
                )
            )
        cursor = payload.get("next_cursor")
        if not cursor:
            return [t for t in toolkits if t.slug and t.name]


def ensure_auth_config(toolkit_slug: str, *, team_id: int | None = None) -> str:
    """Resolve the Composio auth config a toolkit's connections run through, creating the
    managed one on first use. Composio owns the OAuth app; we hold no vendor credentials."""
    existing = _json(
        composio_request(
            "GET",
            f"{AUTH_CONFIGS_PATH}?toolkit_slug={toolkit_slug}&limit=1",
            source=EGRESS_SOURCE,
            team_id=team_id,
        ),
        context="auth config lookup",
    )
    for item in existing.get("items") or []:
        config_id = (item.get("auth_config") or item).get("id")
        if config_id:
            return str(config_id)

    created = _json(
        composio_request(
            "POST",
            AUTH_CONFIGS_PATH,
            source=EGRESS_SOURCE,
            team_id=team_id,
            json={"toolkit": {"slug": toolkit_slug}, "auth_config": {"type": "use_composio_managed_auth"}},
        ),
        context="auth config creation",
    )
    config_id = (created.get("auth_config") or {}).get("id")
    if not config_id:
        raise ComposioError(f"Composio returned no auth config id for '{toolkit_slug}'")
    return str(config_id)


def start_connection_link(
    *, user_id: str, auth_config_id: str, callback_url: str, team_id: int | None = None
) -> ConnectionLink:
    """Begin a hosted connection for one user and toolkit.

    Uses `/connected_accounts/link` rather than the older `/connected_accounts`: Composio retired
    managed-auth OAuth on the latter, and the hosted flow is what shows the user the consent step.
    """
    payload = _json(
        composio_request(
            "POST",
            CONNECTED_ACCOUNTS_LINK_PATH,
            source=EGRESS_SOURCE,
            team_id=team_id,
            json={"user_id": user_id, "auth_config_id": auth_config_id, "callback_url": callback_url},
        ),
        context="connection link",
    )
    redirect_url = payload.get("redirect_url") or payload.get("redirectUrl") or ""
    if not redirect_url:
        raise ComposioError("Composio returned no redirect URL for the connection")
    return ConnectionLink(redirect_url=redirect_url, connected_account_id=str(payload.get("id") or ""))


def session_config_fingerprint(toolkit_slugs: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(toolkit_slugs)).encode()).hexdigest()[:32]


def _session_payload(*, user_id: str, toolkit_slugs: list[str], callback_url: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "toolkits": {"enable": sorted(toolkit_slugs)},
        # Composio enables a remote sandbox by default, which would hand every agent
        # COMPOSIO_REMOTE_BASH_TOOL and COMPOSIO_REMOTE_WORKBENCH as a side effect of connecting,
        # say, HubSpot. Agents already have their own sandbox; this one would be off-platform and
        # outside our policy engine, so it stays off.
        "workbench": {"enable": False},
        "manage_connections": {
            "enable": True,
            "callback_url": callback_url,
            # Deleting a user's connected account is not something an agent should be able to do
            # on its own; connections are managed from project settings.
            "enable_connection_removal": False,
        },
    }


def create_session(*, user_id: str, toolkit_slugs: list[str], callback_url: str, team_id: int) -> SessionInfo:
    """Mint a tool-router session covering exactly the toolkits the user has connected.

    Sessions persist on Composio's side, so callers reuse a stored one and only come back here
    when the connected set changes (`session_config_fingerprint`).
    """
    payload = _json(
        composio_request(
            "POST",
            SESSION_PATH,
            source=EGRESS_SOURCE,
            team_id=team_id,
            json=_session_payload(user_id=user_id, toolkit_slugs=toolkit_slugs, callback_url=callback_url),
        ),
        context="session creation",
    )
    mcp = payload.get("mcp") or {}
    session_id = payload.get("session_id") or ""
    mcp_url = mcp.get("url") or ""
    if not session_id or not mcp_url:
        raise ComposioError("Composio returned an incomplete session")
    return SessionInfo(
        session_id=str(session_id), mcp_url=str(mcp_url), config_version=int(payload.get("config_version") or 0)
    )


def composio_executed_tools(tool_name: str, arguments: Any) -> list[str]:
    """The real tool slugs behind one router call, for policy and audit.

    A Composio session advertises meta-tools, so `tools/call` always names something like
    `COMPOSIO_MULTI_EXECUTE_TOOL` while the tool the agent actually wants is in the arguments —
    up to 50 of them in one call, since multi-execute runs a batch in parallel. Without
    unwrapping, every Composio call would audit as one opaque name and per-tool policy would
    never match. Callers must evaluate *every* returned slug and reject the whole call if any is
    disallowed: the batch is not partially executable.

    Non-execute meta-tools (search, schema lookup) return their own name, so they stay
    policy-visible as themselves. An execute call we can't parse also returns the meta-tool name,
    which no policy row names — and unknown tools resolve to `needs_approval`, so a schema change
    on Composio's side fails closed rather than silently waving a batch through.
    """
    if tool_name not in EXECUTE_TOOL_NAMES or not isinstance(arguments, dict):
        return [tool_name]

    slugs = [
        call["tool_slug"]
        for call in (arguments.get("tools") or [])
        if isinstance(call, dict) and isinstance(call.get("tool_slug"), str) and call["tool_slug"]
    ]
    # Single-execute variants put the slug at the top level instead of in a batch.
    top_level = arguments.get("tool_slug")
    if isinstance(top_level, str) and top_level:
        slugs.append(top_level)

    return slugs or [tool_name]


def composio_enabled() -> bool:
    """Composio is on wherever a key is configured. There is no separate switch: a key present but
    deliberately inert would be a state nobody can reason about from the outside."""
    return is_composio_configured()
