"""
Facade API for mcp_store.

This is the ONLY module other apps are allowed to import.
"""

import uuid
from collections.abc import Iterable

import structlog

from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo
from products.mcp_store.backend.models import MCPServerInstallation

logger = structlog.get_logger(__name__)


def unauthorized_installation_ids(team_id: int, user_id: int, candidate_ids: Iterable[str]) -> list[str]:
    """Return the subset of `candidate_ids` the caller must REJECT — installation
    ids not owned by this (team, user). Ownership is keyed by `(team_id, user_id)`
    because `MCPServerInstallation` is user-scoped: an installation's stored bearer
    belongs to the user who connected it. Callers use this to authorize a *reference*
    to a shared connection (e.g. `spec.mcps[].connection`) so a user can't point an
    agent at a teammate's stored credential by guessing its UUID.

    Ownership-only — does not filter on enabled/ready state. An id that is invalid,
    unknown, or owned by someone else is returned as unauthorized, so callers fail
    closed by rejecting any id this returns.
    """
    candidates = [str(c) for c in candidate_ids if c]
    if not candidates:
        return []
    parsed: dict[str, uuid.UUID | None] = {}
    for c in candidates:
        try:
            parsed[c] = uuid.UUID(c)
        except (ValueError, TypeError):
            parsed[c] = None
    owned = {
        str(r)
        for r in MCPServerInstallation.objects.filter(
            team_id=team_id,
            user_id=user_id,
            id__in=[u for u in parsed.values() if u is not None],
        ).values_list("id", flat=True)
    }
    return [c for c, u in parsed.items() if u is None or str(u) not in owned]


def _resolve_name(installation: MCPServerInstallation) -> str:
    if installation.display_name:
        return installation.display_name
    if installation.template and installation.template.name:
        return installation.template.name
    return installation.url


def _is_oauth_ready(installation: MCPServerInstallation) -> bool:
    if installation.auth_type != "oauth":
        return True
    sensitive = installation.sensitive_configuration or {}
    if sensitive.get("needs_reauth"):
        return False
    if not sensitive.get("access_token"):
        return False
    return True


def get_active_installations(team_id: int, user_id: int) -> list[ActiveInstallationInfo]:
    """Return active, ready-to-use MCP installations for a user.

    Filters out disabled installations and OAuth installations that
    need reauthorization or are still pending token exchange.
    """
    try:
        installations = MCPServerInstallation.objects.filter(
            team_id=team_id, user_id=user_id, is_enabled=True
        ).select_related("template")
    except Exception as e:
        logger.warning("Error fetching MCP installations", error=str(e), team_id=team_id)
        return []

    results: list[ActiveInstallationInfo] = []
    for installation in installations:
        if not _is_oauth_ready(installation):
            logger.debug(
                "Skipping MCP installation not ready",
                installation_id=str(installation.id),
            )
            continue

        results.append(
            ActiveInstallationInfo(
                id=str(installation.id),
                name=_resolve_name(installation),
                proxy_path=f"/api/environments/{team_id}/mcp_server_installations/{installation.id}/proxy/",
            )
        )

    logger.debug("Found active MCP installations", count=len(results), team_id=team_id)
    return results
