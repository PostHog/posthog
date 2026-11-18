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

from collections.abc import Mapping

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.api import get_github_team_roster

logger = structlog.get_logger(__name__)


# Matches the vocabulary ``RoleExternalReference.provider`` uses for the same external-group idea.
GITHUB_PROVIDER = "github"


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
