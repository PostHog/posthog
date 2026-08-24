"""
Facade API for mcp_store.

This is the ONLY module other apps are allowed to import.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable

from django.db.models import Q

import structlog

from products.mcp_store.backend.agents import (
    built_in_agent_key_for_task_origin,
    create_gateway_agent_token,
    credential_owner_eligible,
    get_built_in_agent,
    is_builtin_agent_enforcement_enabled,
)
from products.mcp_store.backend.facade.contracts import ActiveInstallation
from products.mcp_store.backend.gateway import (
    agent_grant_owner_label,
    agent_grant_proxy_path,
    installation_for_agent_access,
    reachable_agent_grants,
)
from products.mcp_store.backend.models import (
    MCPServerInstallation,
    MCPServerInstallationTool,
    MCPServiceAccount,
    MCPServiceAccountServerAccess,
)
from products.mcp_store.backend.policy import GatewayCaller, PolicyContext

logger = structlog.get_logger(__name__)


def resolve_member_tool_states(
    installation_id: str,
    team_id: int,
    gateway_server_id: uuid.UUID | None,
    user_id: int | None = None,
) -> dict[str, str]:
    """Return a {tool_name: effective_state} map for an installation.

    States resolve through the gateway policy engine when the installation is
    registered with a gateway (org rules → team default → the user's scope);
    unregistered installations fall back to the cached per-tool approval state.
    Rows with `removed_at` set surface as `"do_not_use"` so the agent can't
    call them even if the cached approval state was previously `approved` —
    if the tool is gone upstream, it's gone. Anything not in the map is
    treated as `needs_approval` by the caller (explicit opt-in for freshly
    discovered tools)."""
    rows = MCPServerInstallationTool.objects.filter(installation_id=installation_id).values(
        "tool_name", "annotations", "approval_state", "removed_at"
    )
    legacy = {row["tool_name"]: ("do_not_use" if row["removed_at"] else row["approval_state"]) for row in rows}

    if gateway_server_id is None or user_id is None:
        return legacy

    context = PolicyContext(
        team_id=team_id,
        caller=GatewayCaller(kind="member", user_id=user_id),
        gateway_server_id=gateway_server_id,
        legacy_rows={row["tool_name"]: row["approval_state"] for row in rows if row["removed_at"] is None},
    )
    resolved: dict[str, str] = {}
    for row in rows:
        if row["removed_at"]:
            resolved[row["tool_name"]] = "do_not_use"
        else:
            resolved[row["tool_name"]] = context.resolve(row["tool_name"], row["annotations"]).state
    return resolved


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


def _to_info(installation: MCPServerInstallation, team_id: int) -> ActiveInstallation:
    return ActiveInstallation(
        id=str(installation.id),
        name=_resolve_name(installation),
        proxy_path=f"/api/environments/{team_id}/mcp_server_installations/{installation.id}/proxy/",
        scope=installation.scope,
    )


def _mounts_for_agent_run(
    team_id: int,
    agent_account: MCPServiceAccount,
    credential_owner_id: int | None,
    allowed_gateway_server_ids: list[str] | None = None,
) -> list[tuple[MCPServiceAccountServerAccess, MCPServerInstallation]]:
    """The (grant, credential) pairs this run mounts.

    Health resolution runs before per-server precedence, not after. A grant only
    becomes a candidate once its credential still resolves, is enabled, sits on a
    server the team has left on, and (for OAuth) holds a usable token. Precedence
    is then applied over what survived, so a broken credential of the run's own
    owner falls out of the way of teammates' working team shares instead of
    suppressing them and mounting nothing for that server.

    Among the survivors of one server, the run's own credential owner wins
    outright, so the run acts through its own person's connection rather than
    borrowing one. Servers the owner has no working grant for mount every
    surviving team share side by side.

    That precedence is the default mount choice, not a gateway invariant: the
    agent catalog lists every reachable grant and the proxy's `credential_owner`
    query parameter lets a run name a teammate's team share instead. Selection
    is confined to the grants the run already reaches, so it never escalates.

    `allowed_gateway_server_ids` narrows the mounts to the listed gateway
    servers (a scout's per-scout selection). It gates every grant regardless of
    scope, so a run that passes it mounts exactly the selected servers and
    nothing else. None leaves mounts unfiltered; an empty list mounts nothing.
    """
    allowed = {str(server_id) for server_id in allowed_gateway_server_ids or []}
    rows = (
        MCPServiceAccountServerAccess.objects.for_team(team_id)
        .filter(service_account=agent_account)
        .filter(reachable_agent_grants(team_id, credential_owner_id))
        .select_related("installation__template", "installation__gateway_server", "user")
        .order_by("created_at", "id")
    )

    healthy_by_server: dict[uuid.UUID, list[tuple[MCPServiceAccountServerAccess, MCPServerInstallation]]] = defaultdict(
        list
    )
    for access in rows:
        if allowed_gateway_server_ids is not None and str(access.gateway_server_id) not in allowed:
            continue
        # Same resolution the gateway proxy and the API serializers use, so a
        # grant whose credential drifted off its team, server, or owner is
        # dropped here too instead of being mounted into the sandbox.
        installation = installation_for_agent_access(access)
        if installation is None or not installation.is_enabled:
            continue
        # The admin kill switch overrides grants: a server turned off for the
        # team is withheld from agents too.
        if installation.gateway_server is None or not installation.gateway_server.is_team_enabled:
            continue
        if not _is_oauth_ready(installation):
            continue
        healthy_by_server[access.gateway_server_id].append((access, installation))

    mounts: list[tuple[MCPServiceAccountServerAccess, MCPServerInstallation]] = []
    for server_mounts in healthy_by_server.values():
        own = (
            [(access, installation) for access, installation in server_mounts if access.user_id == credential_owner_id]
            if credential_owner_id
            else []
        )
        mounts.extend(own or server_mounts)
    return mounts


def _agent_installation_infos(
    agent_account: MCPServiceAccount,
    mounts: list[tuple[MCPServiceAccountServerAccess, MCPServerInstallation]],
    credential_owner_id: int | None,
) -> list[ActiveInstallation]:
    if not mounts:
        return []
    proxy_token = create_gateway_agent_token(agent_account, credential_owner_id=credential_owner_id)
    mounts_per_server = Counter(access.gateway_server_id for access, _installation in mounts)

    infos: list[ActiveInstallation] = []
    for access, installation in mounts:
        name = _resolve_name(installation)
        if mounts_per_server[access.gateway_server_id] > 1:
            # Sandboxes key MCP servers by name, so two members' credentials for
            # the same server need distinct ones.
            name = f"{name} ({agent_grant_owner_label(access)})"
        infos.append(
            ActiveInstallation(
                id=str(installation.id),
                name=name,
                proxy_path=agent_grant_proxy_path(access),
                scope=installation.scope,
                proxy_token=proxy_token,
            )
        )
    return infos


def get_active_installations(team_id: int, user_id: int, *, include_shared: bool = False) -> list[ActiveInstallation]:
    """Return active, ready-to-use MCP installations a user can mount.

    Personal installations owned by the user by default; ``include_shared`` adds the
    team's shared-scope installations, mirroring what ``get_installations_for_sandbox``
    resolves for an unmapped run. Filters out disabled installations and OAuth
    installations that need reauthorization or are still pending token exchange.
    """
    scope_filter = Q(scope="personal", user_id=user_id)
    if include_shared:
        scope_filter |= Q(scope="shared")
    try:
        # list() evaluates the lazy queryset here so DB errors hit this handler.
        installations = list(
            MCPServerInstallation.objects.filter(team_id=team_id, is_enabled=True)
            .filter(scope_filter)
            .filter(Q(gateway_server__isnull=True) | Q(gateway_server__is_team_enabled=True))
            .exclude(gateway_server__member_revocations__user_id=user_id)
            .select_related("template")
        )
    except Exception as e:
        logger.warning("Error fetching MCP installations", error=str(e), team_id=team_id)
        return []

    results: list[ActiveInstallation] = []
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
    credential_owner_id: int | None = None,
    allowed_gateway_server_ids: list[str] | None = None,
) -> list[ActiveInstallation]:
    """Return MCP installations for sandbox agent use.

    Generic tasks retain the legacy team-shared installation behavior. A
    server-stamped built-in agent task gets only the credentials explicitly
    delegated through its service-account grants: those granted by
    ``credential_owner_id`` (the person whose credentials the run may borrow,
    not necessarily the user it acts as) plus any member's team-scoped grants,
    and only while the gateway server stays enabled for the team. An agent task
    with no credential owner mounts team-scoped grants alone. A named owner's
    eligibility (active user with current effective team access) is re-checked
    on every call, so an offboarded owner's grants stop mounting even though
    the grant rows persist. Origin alone is not
    trusted: the persisted task agent key must match the origin mapping. A
    mapped origin without that marker gets no MCP Store installations. Built-in agent
    handling is gated per team on the `mcp-gateway` rollout flag; teams
    without it resolve mapped origins like unmapped tasks. Unmapped origins
    retain the legacy member behavior and optionally include the user's
    personal installations when ``include_personal`` is True and a ``user_id``
    is provided. When the user has a ready personal installation for the same
    URL as a shared one, only the personal one is returned — the user acts as
    themselves rather than through the shared credential.

    ``allowed_gateway_server_ids`` narrows the agent mounts to the listed
    gateway servers regardless of grant scope (a scout's per-scout selection);
    see ``_mounts_for_agent_run``. It only applies on the agent path.
    """
    try:
        base_queryset = MCPServerInstallation.objects.filter(team_id=team_id, is_enabled=True).select_related(
            "template", "gateway_server"
        )

        mapped_agent_key = built_in_agent_key_for_task_origin(task_origin or "")
        if mapped_agent_key is not None and not is_builtin_agent_enforcement_enabled(team_id):
            # Rollout gate: until the gateway ships for this team, built-in
            # agent origins keep the legacy member resolution below.
            mapped_agent_key = None
        if mapped_agent_key is not None and task_agent_key != mapped_agent_key:
            logger.warning(
                "Refusing MCP installations for an unstamped built-in agent task",
                team_id=team_id,
                task_origin=task_origin,
            )
            return []

        agent_key = mapped_agent_key
        agent_account = get_built_in_agent(team_id, agent_key) if agent_key is not None else None
        if agent_key is not None and agent_account is not None and agent_account.status != "active":
            return []

        installations: list[MCPServerInstallation] = []
        agent_mounts: list[tuple[MCPServiceAccountServerAccess, MCPServerInstallation]] = []
        if agent_key is not None:
            if agent_account is not None:
                if credential_owner_id is not None and not credential_owner_eligible(credential_owner_id, team_id):
                    # Grants survive offboarding, so an owner who was deactivated
                    # or lost team access since delegating mounts nothing.
                    logger.warning(
                        "Refusing MCP installations for an ineligible credential owner",
                        team_id=team_id,
                        task_origin=task_origin,
                    )
                else:
                    agent_mounts = _mounts_for_agent_run(
                        team_id, agent_account, credential_owner_id, allowed_gateway_server_ids
                    )
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

    results: list[ActiveInstallation]
    if agent_key is not None:
        results = (
            _agent_installation_infos(agent_account, agent_mounts, credential_owner_id)
            if agent_account is not None
            else []
        )
    else:
        ready = [installation for installation in installations if _is_oauth_ready(installation)]
        if include_personal and user_id is not None:
            personal_urls = {installation.url for installation in ready if installation.scope == "personal"}
            ready = [
                installation
                for installation in ready
                if installation.scope == "personal" or installation.url not in personal_urls
            ]
        results = [_to_info(installation, team_id) for installation in ready]

    logger.debug(
        "Found MCP installations for sandbox",
        count=len(results),
        team_id=team_id,
        include_personal=include_personal,
        task_origin=task_origin,
        has_trusted_agent_key=agent_key is not None,
    )
    return results


def get_sandbox_mcp_server_names(
    team_id: int,
    *,
    user_id: int | None = None,
    include_personal: bool = False,
    task_origin: str | None = None,
    task_agent_key: str | None = None,
    credential_owner_id: int | None = None,
    allowed_gateway_server_ids: list[str] | None = None,
) -> list[str]:
    """The names of the servers ``get_installations_for_sandbox`` would mount, in mount order.

    For callers that steer an agent at its mounted servers by name before the sandbox launches
    (the Signals scout run prompt), without being handed the mount credentials. Implemented as a
    projection of the full resolution so the two can never disagree on what mounts; the signed
    proxy token that resolution derives is stateless, so discarding it here spends nothing.
    """
    return [
        installation.name
        for installation in get_installations_for_sandbox(
            team_id,
            user_id=user_id,
            include_personal=include_personal,
            task_origin=task_origin,
            task_agent_key=task_agent_key,
            credential_owner_id=credential_owner_id,
            allowed_gateway_server_ids=allowed_gateway_server_ids,
        )
    ]
