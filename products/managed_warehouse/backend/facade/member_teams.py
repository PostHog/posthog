"""Which projects a member can reach in hoglake, as hogtower's team-scoped tokens see them."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.models import Organization, User

__all__ = [
    "member_teams_push_enabled",
    "refresh_member_teams",
    "visible_member_teams",
]


def member_teams_push_enabled() -> bool:
    """Whether PostHog keeps hogtower's copy of each member's projects current."""
    from products.managed_warehouse.backend import member_teams

    return member_teams.is_enabled()


def visible_member_teams(organization: Organization, user: User) -> dict[int, str]:
    """The projects ``user`` can see in ``organization``, each with ``read`` or ``write``."""
    from products.managed_warehouse.backend import member_teams

    return member_teams.member_teams(organization, user)


def refresh_member_teams(organization_id: str, user_uuid: str) -> bool:
    """Push one member's projects to hogtower now. False when hogtower could not take it."""
    from products.managed_warehouse.backend import member_teams

    try:
        member_teams.push_member(organization_id, user_uuid)
    except member_teams.MemberTeamsPushError:
        return False
    return True
