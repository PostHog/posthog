"""
Facade API for mcp_store.

This is the ONLY module other apps are allowed to import.
"""

import uuid

import structlog

from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo
from products.mcp_store.backend.models import MCPServerInstallation

logger = structlog.get_logger(__name__)


def _valid_uuid_strings(installation_ids: list[str]) -> list[str]:
    valid: list[str] = []
    for item in installation_ids:
        try:
            uuid.UUID(item)
        except (ValueError, AttributeError, TypeError):
            logger.warning("Skipping malformed MCP installation id", installation_id=repr(item))
            continue
        valid.append(item)
    return valid


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


def get_active_installations(
    team_id: int,
    user_id: int,
    *,
    installation_ids: list[str] | None = None,
) -> list[ActiveInstallationInfo]:
    """Return active, ready-to-use MCP installations for a user.

    Filters out disabled installations and OAuth installations that
    need reauthorization or are still pending token exchange.
    """
    if installation_ids is not None:
        # Drop malformed ids instead of letting the UUID cast blow up the whole launch —
        # a bad selection should degrade to "that install isn't mounted", not a hard failure.
        installation_ids = _valid_uuid_strings(installation_ids)
        if not installation_ids:
            return []

    try:
        installations_qs = MCPServerInstallation.objects.filter(
            team_id=team_id, user_id=user_id, is_enabled=True
        ).select_related("template")
        if installation_ids is not None:
            installations_qs = installations_qs.filter(id__in=installation_ids)
        installations = list(installations_qs)
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
