"""Aggregated MCP gateway: one team-scoped access point over all connected servers.

Resolution: a caller sees the team's shared installations plus their own
personal ones (enabled and credential-ready only); when both exist for the
same URL the personal one wins, so the user acts as themselves rather than
through the shared credential.

Namespacing: tools are exposed as ``{server_slug}/{tool_name}``. Slugs are
computed on the fly from the installation display name; collisions within the
resolved set get deterministic ``-2``/``-3`` suffixes ordered by ``created_at``
then id.

Dispatch (shared by the JSON-RPC endpoint, the REST endpoint, and the facade):
resolve → enforce approval → refresh token (single-flight) → SSRF check →
upstream ``tools/call`` → analytics → result. Only metadata is ever logged or
captured — never tool arguments, results, or credentials.
"""

import time
from typing import Any

from django.conf import settings
from django.db.models import Q

import structlog

from posthog.models import Team, User

from .analytics import base_server_slug, installation_display_name, report_mcp_tool_call
from .client import UpstreamToolCallError, call_upstream_tool
from .facade.contracts import (
    GatewayCallResult,
    GatewayServerInfo,
    GatewayToolBlockedError,
    GatewayToolInfo,
    GatewayToolNeedsApprovalError,
    GatewayToolNotFoundError,
    GatewayUpstreamError,
)
from .models import MCPServerInstallation, MCPServerInstallationTool
from .oauth import TokenRefreshError, is_token_expiring, refresh_installation_token_single_flight

logger = structlog.get_logger(__name__)


def is_credential_ready(installation: MCPServerInstallation) -> bool:
    """True when the installation can authenticate upstream without user action."""
    if installation.auth_type != "oauth":
        return True
    sensitive = installation.sensitive_configuration or {}
    if sensitive.get("needs_reauth"):
        return False
    if not sensitive.get("access_token"):
        return False
    return True


def resolve_active_installations(
    team_id: int,
    *,
    user_id: int | None = None,
    include_personal: bool = False,
) -> list[MCPServerInstallation]:
    """Resolve the installation set for a caller.

    Shared (team-wide) installations, optionally united with the user's
    personal ones. Disabled and credential-pending installations are dropped;
    a ready personal installation shadows a shared one for the same URL.
    """
    scope_filter = Q(scope="shared")
    if include_personal and user_id is not None:
        scope_filter = scope_filter | Q(scope="personal", user_id=user_id)

    installations = list(
        MCPServerInstallation.objects.filter(team_id=team_id, is_enabled=True)
        .filter(scope_filter)
        .select_related("template")
    )

    ready = [installation for installation in installations if is_credential_ready(installation)]
    if include_personal and user_id is not None:
        personal_urls = {installation.url for installation in ready if installation.scope == "personal"}
        ready = [
            installation
            for installation in ready
            if installation.scope == "personal" or installation.url not in personal_urls
        ]
    return ready


def compute_server_slugs(
    installations: list[MCPServerInstallation],
) -> list[tuple[MCPServerInstallation, str]]:
    """Assign a unique slug to every installation in a resolved set.

    Deterministic: installations are ordered by ``created_at`` then id, the
    first taker keeps the bare slug, later collisions get ``-2``, ``-3``, …
    """
    ordered = sorted(installations, key=lambda installation: (installation.created_at, str(installation.id)))
    used: set[str] = set()
    result: list[tuple[MCPServerInstallation, str]] = []
    for installation in ordered:
        base = base_server_slug(installation)
        slug = base
        suffix = 1
        while slug in used:
            suffix += 1
            slug = f"{base}-{suffix}"
        used.add(slug)
        result.append((installation, slug))
    return result


def _tool_info(tool: MCPServerInstallationTool, installation: MCPServerInstallation, slug: str) -> GatewayToolInfo:
    return GatewayToolInfo(
        name=f"{slug}/{tool.tool_name}",
        server=GatewayServerInfo(
            slug=slug,
            display_name=installation_display_name(installation),
            installation_id=str(installation.id),
            scope=installation.scope,
        ),
        tool_name=tool.tool_name,
        description=tool.description,
        input_schema=tool.input_schema or {},
        approval_state=tool.approval_state,
    )


def list_gateway_tools(
    team_id: int,
    user_id: int,
    *,
    search: str | None = None,
    name: str | None = None,
) -> list[GatewayToolInfo]:
    """The merged, namespaced tool catalog for a caller (from the Postgres cache).

    ``do_not_use`` tools are hidden; ``needs_approval`` tools are listed but
    blocked at call time (matching the per-installation proxy semantics).
    """
    installations = resolve_active_installations(team_id, user_id=user_id, include_personal=True)
    slugged = compute_server_slugs(installations)
    installations_by_id = {installation.id: (installation, slug) for installation, slug in slugged}

    tools = (
        MCPServerInstallationTool.objects.filter(
            installation_id__in=installations_by_id.keys(), removed_at__isnull=True
        )
        .exclude(approval_state="do_not_use")
        .order_by("tool_name")
    )

    infos: list[GatewayToolInfo] = []
    for tool in tools:
        installation, slug = installations_by_id[tool.installation_id]
        infos.append(_tool_info(tool, installation, slug))
    infos.sort(key=lambda info: info.name)

    if name is not None:
        return [info for info in infos if info.name == name]

    if search:
        needle = search.lower()
        name_matches: list[GatewayToolInfo] = []
        description_matches: list[GatewayToolInfo] = []
        for info in infos:
            if needle in info.name.lower():
                name_matches.append(info)
            elif needle in info.description.lower():
                description_matches.append(info)
        return name_matches + description_matches

    return infos


def gateway_approval_url(team_id: int) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/settings/mcp-servers"


def _resolve_tool_for_call(
    team_id: int, user_id: int, tool: str
) -> tuple[MCPServerInstallation, str, MCPServerInstallationTool]:
    server_slug, separator, tool_name = tool.partition("/")
    if not separator or not server_slug or not tool_name:
        raise GatewayToolNotFoundError(f"Unknown tool '{tool}' — expected '{{server_slug}}/{{tool_name}}'")

    installations = resolve_active_installations(team_id, user_id=user_id, include_personal=True)
    installation = next(
        (candidate for candidate, slug in compute_server_slugs(installations) if slug == server_slug), None
    )
    if installation is None:
        raise GatewayToolNotFoundError(f"Unknown server '{server_slug}'")

    tool_row = installation.tools.filter(tool_name=tool_name, removed_at__isnull=True).first()
    if tool_row is None:
        raise GatewayToolNotFoundError(f"Tool '{tool_name}' is not available on server '{server_slug}'")
    return installation, server_slug, tool_row


def _ensure_ready_credentials(installation: MCPServerInstallation) -> None:
    sensitive = installation.sensitive_configuration or {}
    if sensitive.get("needs_reauth"):
        raise GatewayUpstreamError("Installation needs re-authentication", error_type="auth_failed")
    if installation.auth_type == "oauth":
        if not sensitive.get("access_token"):
            raise GatewayUpstreamError("No credentials configured", error_type="auth_failed")
        if is_token_expiring(sensitive):
            try:
                refresh_installation_token_single_flight(installation)
            except TokenRefreshError as exc:
                raise GatewayUpstreamError("Authentication failed", error_type="auth_failed") from exc
    elif installation.auth_type == "api_key" and not sensitive.get("api_key"):
        raise GatewayUpstreamError("No credentials configured", error_type="auth_failed")


def call_gateway_tool(
    *,
    team: Team,
    user: User,
    tool: str,
    arguments: dict[str, Any],
    consumer: str | None = None,
) -> GatewayCallResult:
    """Shared dispatch path for the JSON-RPC endpoint, the REST endpoint, and the facade.

    Raises ``GatewayToolNotFoundError`` / ``GatewayToolNeedsApprovalError`` /
    ``GatewayToolBlockedError`` / ``GatewayUpstreamError`` (see facade contracts);
    callers map these to their transport's error shape.
    """
    installation, server_slug, tool_row = _resolve_tool_for_call(team.id, user.id, tool)

    started_at = time.monotonic()
    is_error = True
    error_type: str | None = "unknown"
    try:
        if tool_row.approval_state == "needs_approval":
            error_type = "needs_approval"
            raise GatewayToolNeedsApprovalError(
                f"Tool '{tool}' requires approval before it can be called",
                approval_url=gateway_approval_url(team.id),
            )
        if tool_row.approval_state == "do_not_use":
            error_type = "blocked"
            raise GatewayToolBlockedError(f"Tool '{tool}' has been disabled by the user")

        try:
            _ensure_ready_credentials(installation)
            result = call_upstream_tool(installation, tool_row.tool_name, arguments)
        except GatewayUpstreamError as exc:
            error_type = exc.error_type
            raise
        except UpstreamToolCallError as exc:
            error_type = exc.error_type
            raise GatewayUpstreamError(str(exc), error_type=exc.error_type) from exc

        is_error = bool(result.get("isError", False))
        error_type = "tool_error" if is_error else None
        structured_content = result.get("structuredContent")
        return GatewayCallResult(
            content=result.get("content") or [],
            is_error=is_error,
            server_slug=server_slug,
            tool_name=tool_row.tool_name,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            structured_content=structured_content if isinstance(structured_content, dict) else None,
        )
    finally:
        report_mcp_tool_call(
            user,
            team,
            tool_name=tool,
            source="gateway",
            server_slug=server_slug,
            installation=installation,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            is_error=is_error,
            error_type=error_type,
            consumer=consumer,
        )
