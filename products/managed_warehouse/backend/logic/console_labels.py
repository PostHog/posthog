"""Readable labels for the principals and client sources that appear in warehouse usage."""

from __future__ import annotations

import re
from collections.abc import Iterable

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

SOURCE_LABELS = {
    "posthog-sql-editor": "SQL editor",
    "posthog-materialization": "Materialized views",
    "posthog-import": "Data imports",
    "posthog-console": "Warehouse console",
    "endpoints": "Endpoints",
    "posthog": "PostHog",
    "unknown": "Unknown",
}

# Longest prefixes first: the first match wins.
_PRINCIPAL_PREFIX_LABELS = (
    ("posthog:sql-editor-schema-discovery", "SQL editor schema discovery"),
    ("posthog:sql-editor", "SQL editor"),
    ("posthog:trino-materialization", "PostHog materialization"),
    ("posthog:trino-compile-check", "PostHog view compile check"),
    ("posthog:trino-model-aliases", "PostHog model aliases"),
    ("posthog:model-alias", "PostHog model aliases"),
    ("posthog:trino", "PostHog"),
)

SQL_EDITOR_PRINCIPAL = re.compile(r"posthog:sql-editor:team:(?P<team_id>\d+):user:(?P<user_id>\d+)")
# Any PostHog principal that names a project: posthog:<kind>:team:<team id>, with optional trailing parts.
TEAM_PRINCIPAL = re.compile(r"posthog:(?P<kind>[a-z0-9-]+):team:(?P<team_id>\d+)(?::.*)?")

# Principal kinds that name the same thing as a client source, so they share the source's label.
_KIND_SOURCES = {
    "materialization": "posthog-materialization",
    "trino-materialization": "posthog-materialization",
    "import": "posthog-import",
    "data-imports": "posthog-import",
}


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def sql_editor_user_ids(principals: Iterable[str]) -> set[int]:
    return {int(m.group("user_id")) for p in principals if (m := SQL_EDITOR_PRINCIPAL.fullmatch(p))}


def principal_team_ids(principals: Iterable[str]) -> set[int]:
    return {int(m.group("team_id")) for p in principals if (m := TEAM_PRINCIPAL.fullmatch(p))}


def team_display_names(organization_id: str, team_ids: set[int]) -> dict[int, str]:
    """Names of the projects in the organization. Other ids are left out."""
    if not team_ids:
        return {}
    return dict(Team.objects.filter(organization_id=organization_id, pk__in=team_ids).values_list("pk", "name"))


def _kind_label(kind: str) -> str | None:
    source = _KIND_SOURCES.get(kind, f"posthog-{kind}")
    if source in SOURCE_LABELS:
        return SOURCE_LABELS[source]
    for prefix, label in _PRINCIPAL_PREFIX_LABELS:
        if f"posthog:{kind}" == prefix:
            return label
    return None


def member_display_names(organization_id: str, user_ids: set[int]) -> dict[int, str]:
    """Display names for the ids that belong to members of the organization. Other ids are left out."""
    if not user_ids:
        return {}
    memberships = OrganizationMembership.objects.filter(organization_id=organization_id, user_id__in=user_ids)
    return {m.user_id: m.user.first_name or m.user.email for m in memberships.select_related("user")}


def principal_label(principal: str, member_names: dict[int, str], team_names: dict[int, str] | None = None) -> str:
    """Label a Trino principal. Anything that PostHog did not issue stays raw.

    A principal that names a project reads "<kind> · <project name>", or "<kind> · Project <id>"
    when the project is not in the organization.
    """
    if not principal.startswith("posthog:"):
        return principal
    match = SQL_EDITOR_PRINCIPAL.fullmatch(principal)
    if match and (name := member_names.get(int(match.group("user_id")))):
        return f"SQL editor · {name}"
    team_match = TEAM_PRINCIPAL.fullmatch(principal)
    if team_match and not SQL_EDITOR_PRINCIPAL.fullmatch(principal) and (kind := _kind_label(team_match.group("kind"))):
        team_id = int(team_match.group("team_id"))
        return f"{kind} · {(team_names or {}).get(team_id, f'Project {team_id}')}"
    for prefix, label in _PRINCIPAL_PREFIX_LABELS:
        if principal == prefix or principal.startswith(prefix + ":"):
            return label
    return "PostHog"
