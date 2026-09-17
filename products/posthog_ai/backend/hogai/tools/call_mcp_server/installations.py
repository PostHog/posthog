from __future__ import annotations

from uuid import UUID

from django.db.models import Q

from posthog.models import Team, User

from products.mcp_store.backend.facade.api import resolve_member_tool_states
from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool
from products.mcp_store.backend.oauth import refresh_installation_token


def _is_row_ready(row: dict) -> bool:
    if row["auth_type"] != "oauth":
        return True
    sensitive = row.get("sensitive_configuration") or {}
    return bool(sensitive.get("access_token")) and not sensitive.get("needs_reauth")


def _get_installations(team: Team, user: User) -> list[dict]:
    """Return the MCP installations available to this user's agent: their
    personal installations plus team-shared ones.

    Per-URL resolution matches the sandbox facade and PostHog Desktop: a ready
    personal installation wins over a shared one (the agent acts as the user
    rather than through a teammate's shared credential), but a dead personal
    row doesn't shadow a working shared one. Unready shared rows are hidden
    entirely — a teammate can't fix someone else's credential, while an
    unready personal row still surfaces so Max can walk the user through
    reauth."""
    rows = [
        dict(row)
        for row in MCPServerInstallation.objects.filter(team=team, is_enabled=True)
        .filter(Q(scope="shared") | Q(user=user))
        # Gateway layer: servers disabled for the team, or turned off for this
        # member by an admin, are invisible to the agent too.
        .filter(Q(gateway_server__isnull=True) | Q(gateway_server__is_team_enabled=True))
        .exclude(gateway_server__member_revocations__user=user)
        .values(
            "id",
            "display_name",
            "url",
            "auth_type",
            "sensitive_configuration",
            "scope",
            "gateway_server_id",
        )
    ]
    ready_shared_by_url = {row["url"]: row for row in rows if row["scope"] == "shared" and _is_row_ready(row)}
    results: list[dict] = []
    for row in rows:
        if row["scope"] == "shared":
            continue
        if _is_row_ready(row) or row["url"] not in ready_shared_by_url:
            results.append(row)
            ready_shared_by_url.pop(row["url"], None)
    results.extend(ready_shared_by_url.values())
    return results


def _get_cached_tools(installation_id: str) -> list[dict]:
    """Return the installation's cached tool list (rows where `removed_at IS NULL`).

    Each row is shaped to match the `tools/list` payload the MCP client would
    return, so the agent code can format it identically whether the data came
    from Postgres or from a fresh upstream call. Approval states are deliberately
    not included: effective states come from `_get_tool_approval_states`, which
    resolves through the gateway policy engine."""
    rows = MCPServerInstallationTool.objects.filter(installation_id=installation_id, removed_at__isnull=True).values(
        "tool_name", "description", "input_schema"
    )
    return [
        {
            "name": row["tool_name"],
            "description": row["description"] or "No description",
            "inputSchema": row["input_schema"] or {},
        }
        for row in rows
    ]


def _get_tool_approval_states(
    installation_id: str,
    team_id: int,
    gateway_server_id: UUID | None,
    user: User | None = None,
) -> dict[str, str]:
    """Return a {tool_name: effective_state} map for an installation.

    See `resolve_member_tool_states` on the mcp_store facade for the resolution
    semantics (gateway policy engine vs. cached per-tool approval state)."""
    return resolve_member_tool_states(
        installation_id,
        team_id,
        gateway_server_id,
        user_id=user.id if user is not None else None,
    )


def _mark_needs_reauth_sync(installation_id: str) -> None:
    try:
        inst = MCPServerInstallation.objects.get(id=installation_id)
    except MCPServerInstallation.DoesNotExist:
        return
    sensitive = inst.sensitive_configuration or {}
    sensitive["needs_reauth"] = True
    inst.sensitive_configuration = sensitive
    inst.save(update_fields=["sensitive_configuration", "updated_at"])


def _refresh_token_sync(installation: dict) -> dict:
    # refresh_installation_token resolves template-or-installation OAuth creds itself,
    # so we don't need to pre-join anything here.
    inst_obj = MCPServerInstallation.objects.get(id=installation["id"])
    return refresh_installation_token(inst_obj)


def _build_server_headers(installations: list[dict]) -> dict[str, dict[str, str]]:
    headers: dict[str, dict[str, str]] = {}
    for inst in installations:
        url = inst["url"]
        auth_type = inst.get("auth_type", "api_key")
        sensitive = inst.get("sensitive_configuration") or {}

        if auth_type == "api_key":
            if api_key := sensitive.get("api_key"):
                headers[url] = {"Authorization": f"Bearer {api_key}"}
        elif auth_type == "oauth":
            if access_token := sensitive.get("access_token"):
                headers[url] = {"Authorization": f"Bearer {access_token}"}

    return headers
