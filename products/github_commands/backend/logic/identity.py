"""Finds the PostHog user behind a GitHub commenter, and the projects they may act in.

The match is on GitHub's numeric user id, never on the login. A login can be renamed and then
claimed by someone else, but the id stays with the account. Only identities that GitHub itself
confirmed to PostHog count: the GitHub account a user connected in PostHog, or the one they log in
with. A login typed into a profile or saved on a project integration does not.
"""

from typing import Literal

from social_django.models import UserSocialAuth

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.user_permissions import UserPermissions


@frozen
class Commenter:
    user_id: int
    # Projects whose GitHub integration uses this installation and that the user is a member of,
    # oldest integration first. Empty when the user belongs to none of them.
    team_ids: tuple[int, ...]


@frozen
class UnresolvedCommenter:
    reason: Literal["unlinked", "ambiguous"]


def resolve_commenter(*, github_user_id: int, installation_id: str) -> Commenter | UnresolvedCommenter:
    user_ids = _linked_user_ids(github_user_id)
    if not user_ids:
        return UnresolvedCommenter(reason="unlinked")
    if len(user_ids) > 1:
        # Two PostHog accounts claim the same GitHub account. Picking one would let the other act
        # with its access, so neither may.
        return UnresolvedCommenter(reason="ambiguous")
    user = User.objects.get(id=next(iter(user_ids)))
    return Commenter(user_id=user.id, team_ids=_member_team_ids(user, installation_id))


def _linked_user_ids(github_user_id: int) -> set[int]:
    integration_user_ids = UserIntegration.objects.filter(
        kind=UserIntegration.IntegrationKind.GITHUB,
        # The id arrives as a JSON number from the GitHub OAuth flow. Older rows may hold a string.
        config__github_user__id__in=[github_user_id, str(github_user_id)],
    ).values_list("user_id", flat=True)
    social_user_ids = UserSocialAuth.objects.filter(provider="github", uid=str(github_user_id)).values_list(
        "user_id", flat=True
    )
    return set(
        User.objects.filter(id__in={*integration_user_ids, *social_user_ids}, is_active=True).values_list(
            "id", flat=True
        )
    )


def _is_member(permissions: UserPermissions, team: Team) -> bool:
    if permissions.team(team).effective_membership_level is None:
        return False
    # A child environment without its own access rows defaults open while the parent project
    # denies the user, so the parent decides too.
    parent = team.parent_team
    return parent is None or permissions.team(parent).effective_membership_level is not None


def _member_team_ids(user: User, installation_id: str) -> tuple[int, ...]:
    team_ids = list(
        dict.fromkeys(
            Integration.objects.filter(kind="github", integration_id=installation_id)
            .order_by("id")
            .values_list("team_id", flat=True)
        )
    )
    teams = Team.objects.filter(id__in=team_ids).select_related("organization", "parent_team__organization")
    teams_by_id = {team.id: team for team in teams}
    permissions = UserPermissions(user)
    organizations = {team.organization_id: team.organization for team in teams_by_id.values()}
    # The product APIs refuse an organization that is pending deletion or inactive, and a member
    # whose email is outside its enforced verified domains, so a comment must not reach those
    # projects either.
    blocked_organization_ids = {
        organization_id
        for organization_id, organization in organizations.items()
        if organization.is_pending_deletion
        or not organization.is_active
        or OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(user.email, organization)
    }
    return tuple(
        team_id
        for team_id in team_ids
        if team_id in teams_by_id
        and teams_by_id[team_id].organization_id not in blocked_organization_ids
        and _is_member(permissions, teams_by_id[team_id])
    )
