"""
Facade API for mcp_store.

This is the ONLY module other apps are allowed to import.
"""

import uuid
from collections.abc import Iterable

from django.db.models import Q

import structlog

from products.mcp_store.backend.agents import (
    built_in_agent_key_for_task_origin,
    create_gateway_agent_token,
    get_agent_product_availability,
    get_built_in_agent,
)
from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo
from products.mcp_store.backend.models import MCPServerInstallation, MCPServiceAccountServerAccess

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


def _to_info(
    installation: MCPServerInstallation,
    team_id: int,
    *,
    agent_proxy_token: str | None = None,
) -> ActiveInstallationInfo:
    if agent_proxy_token is not None and installation.gateway_server_id is not None:
        proxy_path = f"/api/mcp_store/gateway/servers/{installation.gateway_server_id}/proxy/"
    else:
        proxy_path = f"/api/environments/{team_id}/mcp_server_installations/{installation.id}/proxy/"

    return ActiveInstallationInfo(
        id=str(installation.id),
        name=_resolve_name(installation),
        proxy_path=proxy_path,
        scope=installation.scope,
        proxy_token=agent_proxy_token,
    )


def get_active_installations(team_id: int, user_id: int) -> list[ActiveInstallationInfo]:
    """Return active, ready-to-use personal MCP installations for a user.

    Filters out disabled installations and OAuth installations that
    need reauthorization or are still pending token exchange.
    """
    try:
        # list() evaluates the lazy queryset here so DB errors hit this handler.
        installations = list(
            MCPServerInstallation.objects.filter(team_id=team_id, user_id=user_id, is_enabled=True, scope="personal")
            .filter(Q(gateway_server__isnull=True) | Q(gateway_server__is_team_enabled=True))
            .exclude(gateway_server__member_revocations__user_id=user_id)
            .select_related("template")
        )
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
        results.append(_to_info(installation, team_id))

    logger.debug("Found active MCP installations", count=len(results), team_id=team_id)
    return results


def get_installations_for_sandbox(
    team_id: int,
    *,
    user_id: int | None = None,
    include_personal: bool = False,
    task_origin: str | None = None,
    task_agent_key: str | None = None,
) -> list[ActiveInstallationInfo]:
    """Return MCP installations for sandbox agent use.

    Generic tasks retain the legacy team-shared installation behavior. A
    server-stamped built-in agent task gets only the credentials explicitly
    delegated through its service-account grants. Origin alone is not trusted:
    the persisted task agent key must match the origin mapping. A mapped origin
    without that marker gets no MCP Store installations. Unmapped origins
    retain the legacy member behavior and optionally include the user's
    personal installations when ``include_personal`` is True and a ``user_id``
    is provided. When the user has a ready personal installation for the same
    URL as a shared one, only the personal one is returned — the user acts as
    themselves rather than through the shared credential.
    """
    try:
        base_queryset = MCPServerInstallation.objects.filter(team_id=team_id, is_enabled=True).select_related(
            "template", "gateway_server"
        )

        mapped_agent_key = built_in_agent_key_for_task_origin(task_origin or "")
        if mapped_agent_key is not None and task_agent_key != mapped_agent_key:
            logger.warning(
                "Refusing MCP installations for an unstamped built-in agent task",
                team_id=team_id,
                task_origin=task_origin,
            )
            return []

        agent_key = mapped_agent_key
        agent_account = get_built_in_agent(team_id, agent_key) if agent_key is not None else None
        if (
            agent_key is not None
            and agent_account is not None
            and (
                agent_account.status != "active"
                or not get_agent_product_availability(agent_account.team, agent_key).enabled
            )
        ):
            return []

        if agent_key is not None:
            if agent_account is None:
                installations = []
            else:
                access_rows = list(
                    MCPServiceAccountServerAccess.objects.for_team(team_id)
                    .filter(service_account=agent_account)
                    .values_list("installation_id", "gateway_server_id")
                )
                bound_servers = {
                    installation_id: gateway_server_id
                    for installation_id, gateway_server_id in access_rows
                    if installation_id is not None
                }
                legacy_server_ids = {
                    gateway_server_id for installation_id, gateway_server_id in access_rows if installation_id is None
                }
                candidates = list(
                    base_queryset.filter(
                        Q(id__in=bound_servers) | Q(scope="shared", gateway_server_id__in=legacy_server_ids)
                    )
                )
                installations = [
                    installation
                    for installation in candidates
                    if (
                        bound_servers.get(installation.id) == installation.gateway_server_id
                        or (installation.scope == "shared" and installation.gateway_server_id in legacy_server_ids)
                    )
                ]
        else:
            shared_queryset = base_queryset.filter(scope="shared")
            shared_queryset = shared_queryset.filter(
                Q(gateway_server__isnull=True) | Q(gateway_server__is_team_enabled=True)
            )
            if user_id is not None:
                shared_queryset = shared_queryset.exclude(gateway_server__member_revocations__user_id=user_id)
            # list() evaluates the lazy querysets here so DB errors hit this handler.
            installations = list(shared_queryset)
            if include_personal and user_id is not None:
                personal_queryset = (
                    base_queryset.filter(scope="personal", user_id=user_id)
                    .filter(Q(gateway_server__isnull=True) | Q(gateway_server__is_team_enabled=True))
                    .exclude(gateway_server__member_revocations__user_id=user_id)
                )
                installations.extend(personal_queryset)
    except Exception as e:
        logger.warning("Error fetching MCP installations for sandbox", error=str(e), team_id=team_id)
        return []

    ready = [installation for installation in installations if _is_oauth_ready(installation)]
    if include_personal and user_id is not None:
        personal_urls = {installation.url for installation in ready if installation.scope == "personal"}
        ready = [
            installation
            for installation in ready
            if installation.scope == "personal" or installation.url not in personal_urls
        ]

    agent_proxy_token = create_gateway_agent_token(agent_account) if agent_account is not None and ready else None
    results = [
        _to_info(
            installation,
            team_id,
            agent_proxy_token=agent_proxy_token if agent_account is not None else None,
        )
        for installation in ready
    ]

    logger.debug(
        "Found MCP installations for sandbox",
        count=len(results),
        team_id=team_id,
        include_personal=include_personal,
        task_origin=task_origin,
        has_trusted_agent_key=agent_key is not None,
    )
    return results
