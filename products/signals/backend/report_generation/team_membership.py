"""Which teams a person belongs to, so a report can be routed at a team rather than at a name.

Routing input often names a team: a slug in a scout note, a CODEOWNERS entry, an ``owners.yaml``
owner. The reviewer artefact only holds individuals, so this is the step in between, and it is
kept provider-neutral: a membership here is a slug, a display name, and whether the person maintains
the team, none of which is GitHub's. The synced GitHub org roster is the only source behind it today.

Two properties every caller has to carry:

- The roster is a warehouse snapshot, so it is only as fresh as the source's last sync and can lag
  the live team.
- The membership endpoint is off by default (it needs the org Members grant), so a slug with no rows
  means "not synced here", never "no such team".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.access_control.backend.facade.api import (
    likely_role,
    list_external_role_references,
    valid_role_member_user_ids,
    valid_role_member_user_ids_by_role,
)
from products.access_control.backend.facade.contracts import RoleMatchSource
from products.engineering_analytics.backend.facade.api import get_github_team_roster

logger = structlog.get_logger(__name__)


# Matches the vocabulary ``RoleExternalReference.provider`` uses for the same external-group idea.
GITHUB_PROVIDER = "github"
POSTHOG_ROLE_PROVIDER = "posthog_role"


@frozen
class MemberTeam:
    """One team a person belongs to, on one provider."""

    provider: str
    slug: str
    name: str
    is_maintainer: bool


@frozen
class MembershipRoster:
    """The project's team memberships, keyed by the identity a member is matched on."""

    # False when no membership snapshot could be read at all, either unsynced or a failed read.
    synced: bool
    # True when the read itself failed, so a snapshot may well be synced. The two need telling
    # apart: a caller that reports a timeout as "turn the sync on" sends a scout to change a
    # setting that is already right.
    read_failed: bool
    # Lowercased GitHub login -> the teams that login is on, sorted by slug.
    teams_by_login: Mapping[str, tuple[MemberTeam, ...]]
    # Every slug the snapshot holds, including teams with no PostHog member on them, which is what
    # separates "no rows for that team" from "nobody on that team can review here".
    covered_slugs: frozenset[str]

    def teams_for(self, login: str | None) -> tuple[MemberTeam, ...]:
        return self.teams_by_login.get(login, ()) if login else ()


_UNSYNCED = MembershipRoster(synced=False, read_failed=False, teams_by_login={}, covered_slugs=frozenset())
_READ_FAILED = MembershipRoster(synced=False, read_failed=True, teams_by_login={}, covered_slugs=frozenset())


def resolve_membership_roster(team: Team) -> MembershipRoster:
    """The project's team memberships, or an unsynced roster when none can be read.

    Userless on purpose: this resolves the roster server-side for the whole project, the same way
    the member list beside it reads project access straight from the ORM. A scout token is an
    automation rather than a person choosing warehouse sources, and team scoping is the boundary.

    A failed read degrades rather than raising. Routing is one field of a report, so a warehouse
    hiccup must not fail the roster call that also answers "who can review here". It comes back
    marked ``read_failed`` so a caller can offer a retry instead of a sync it does not need.
    """
    try:
        roster = get_github_team_roster(team=team)
    except Exception:
        logger.warning("signals.team_membership.roster_read_failed", team_id=team.pk, exc_info=True)
        return _READ_FAILED
    if not roster.synced:
        return _UNSYNCED

    teams_by_login: dict[str, list[MemberTeam]] = {}
    covered_slugs: set[str] = set()
    for membership in roster.memberships:
        slug = membership.team_slug.lower()
        covered_slugs.add(slug)
        teams_by_login.setdefault(membership.member_handle.lower(), []).append(
            MemberTeam(
                provider=GITHUB_PROVIDER,
                slug=slug,
                name=membership.team_name,
                is_maintainer=membership.is_maintainer,
            )
        )
    return MembershipRoster(
        synced=True,
        read_failed=False,
        teams_by_login={
            login: tuple(sorted(teams, key=lambda member_team: member_team.slug))
            for login, teams in teams_by_login.items()
        },
        covered_slugs=frozenset(covered_slugs),
    )


@frozen
class RoleTeamResolution:
    role_id: UUID
    role_name: str
    provider: str
    slug: str
    user_ids: frozenset[int]


def resolve_role_team(team: Team, team_query: str, *, slug: str) -> RoleTeamResolution | None:
    """Resolve a team query or CODEOWNERS slug to a PostHog role and its valid member user IDs."""
    try:
        matched = likely_role(team_query, organization_id=team.organization_id, provider=GITHUB_PROVIDER)
        if matched is None:
            return None
        user_ids = frozenset(valid_role_member_user_ids(role_id=matched.id))
    except Exception:
        logger.warning("signals.team_membership.role_lookup_failed", team_id=team.pk, exc_info=True)
        return None
    provider = GITHUB_PROVIDER if matched.source == RoleMatchSource.EXTERNAL_REFERENCE else POSTHOG_ROLE_PROVIDER
    return RoleTeamResolution(
        role_id=matched.id,
        role_name=matched.name,
        provider=provider,
        slug=slug,
        user_ids=user_ids,
    )


def resolve_user_mapped_teams(team: Team, user_ids: Sequence[int]) -> dict[int, tuple[MemberTeam, ...]]:
    """Explicitly mapped GitHub teams per user from ``RoleExternalReference``, without warehouse sync."""
    if not user_ids:
        return {}
    try:
        references = list_external_role_references(organization_id=team.organization_id, provider=GITHUB_PROVIDER)
        if not references:
            return {}
        members_by_role = valid_role_member_user_ids_by_role(role_ids={ref.role_id for ref in references})
    except Exception:
        logger.warning("signals.team_membership.mapped_teams_read_failed", team_id=team.pk, exc_info=True)
        return {}

    wanted_users = set(user_ids)
    teams_by_user: dict[int, list[MemberTeam]] = {}
    for ref in references:
        slug = (ref.provider_role_slug or ref.provider_role_id).strip().lower()
        if not slug:
            continue
        member_team = MemberTeam(
            provider=GITHUB_PROVIDER,
            slug=slug,
            name=ref.role_name,
            is_maintainer=False,
        )
        for user_id in members_by_role.get(ref.role_id, frozenset()) & wanted_users:
            teams_by_user.setdefault(user_id, []).append(member_team)
    return {user_id: tuple(sorted(teams, key=lambda item: item.slug)) for user_id, teams in teams_by_user.items()}
