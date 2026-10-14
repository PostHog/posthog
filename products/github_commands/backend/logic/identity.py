"""Finds the PostHog accounts behind a GitHub commenter, and the projects each may act in.

The match is on GitHub's numeric user id, never on the login. A login can be renamed and then
claimed by someone else, but the id stays with the account. Only identities that GitHub itself
confirmed to PostHog count: the GitHub account a user connected in PostHog, or the one they log in
with. A login typed into a profile or saved on a project integration does not.

One GitHub account can be linked to several PostHog accounts, for example a work and a personal one.
Every link needed that GitHub account's approval, so all of them belong to the person behind the
comment. The command picks the project, and the linked account that is a member of it acts there.
"""

from datetime import datetime
from typing import Literal

import structlog
from social_django.models import UserSocialAuth

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.user_permissions import UserPermissions

from products.security.backend.facade.api import access_refused
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Surface

from .commands import ProjectMember

logger = structlog.get_logger(__name__)


@frozen
class Commenter:
    # Projects whose GitHub integration uses this installation, each with a linked account that is a
    # member of it. Oldest integration first, and within a project the most recently linked account
    # first. Empty when no linked account belongs to any of them.
    members: tuple[ProjectMember, ...]


@frozen
class UnresolvedCommenter:
    reason: Literal["unlinked", "refused"]


def _linked_users(github_user_id: int) -> list[User]:
    """The active users linked to the GitHub account, most recently linked first."""
    links = [
        *UserIntegration.objects.filter(
            kind=UserIntegration.IntegrationKind.GITHUB,
            # The id arrives as a JSON number from the GitHub OAuth flow. Older rows may hold a string.
            config__github_user__id__in=[github_user_id, str(github_user_id)],
        ).values_list("user_id", "created_at"),
        *UserSocialAuth.objects.filter(provider="github", uid=str(github_user_id)).values_list("user_id", "created"),
    ]
    linked_at: dict[int, datetime] = {}
    for user_id, created_at in links:
        linked_at[user_id] = max(created_at, linked_at.get(user_id, created_at))
    users = User.objects.filter(id__in=linked_at, is_active=True)
    return sorted(users, key=lambda user: (linked_at[user.id], user.id), reverse=True)


def _is_member(permissions: UserPermissions, team: Team) -> bool:
    if permissions.team(team).effective_membership_level is None:
        return False
    # A child environment without its own access rows defaults open while the parent project
    # denies the user, so the parent decides too.
    parent = team.parent_team
    return parent is None or permissions.team(parent).effective_membership_level is not None


def _member_team_ids(user: User, teams: list[Team]) -> set[int]:
    permissions = UserPermissions(user)
    organizations = {team.organization_id: team.organization for team in teams}
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
    return {
        team.id
        for team in teams
        if team.organization_id not in blocked_organization_ids and _is_member(permissions, team)
    }


def _project_members(users: list[User], installation_id: str) -> tuple[ProjectMember, ...]:
    team_ids = list(
        dict.fromkeys(
            Integration.objects.filter(kind="github", integration_id=installation_id)
            .order_by("id")
            .values_list("team_id", flat=True)
        )
    )
    teams_by_id = Team.objects.select_related("organization", "parent_team__organization").in_bulk(team_ids)
    teams = [teams_by_id[team_id] for team_id in team_ids if team_id in teams_by_id]
    member_team_ids = {user.id: _member_team_ids(user, teams) for user in users}
    # When two linked accounts are members of the same project, the most recently linked one acts
    # there, as in the Slack app: the person linked it last, so it is the one they use.
    return tuple(
        ProjectMember(team_id=team.id, user_id=user.id)
        for team in teams
        for user in users
        if team.id in member_team_ids[user.id]
    )


def resolve_commenter(*, github_user_id: int, installation_id: str) -> Commenter | UnresolvedCommenter:
    users = _linked_users(github_user_id)
    if not users:
        return UnresolvedCommenter(reason="unlinked")
    # The same rule that refuses an account's logins and API keys refuses its commands. Another
    # linked account can still log in, so it can still run commands.
    users = [
        user
        for user in users
        if not access_refused(
            SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site="github_command"
        )
    ]
    if not users:
        return UnresolvedCommenter(reason="refused")
    if len(users) > 1:
        logger.info("github_command_commenter_has_several_accounts", account_count=len(users))
    return Commenter(members=_project_members(users, installation_id))
