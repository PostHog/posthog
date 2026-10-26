from typing import cast

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication


class ScoutCanonicalTeamAccessPermission(BasePermission):
    """Authorize requests against the project that owns the scout data."""

    message = "You don't have access to the project that owns this data."

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_view = cast(TeamAndOrgViewSetMixin, view)
        if not request.user.is_authenticated:
            # Unreachable while `IsAuthenticated` runs ahead of this class, but deny rather than
            # allow, so this class can never be the reason an anonymous request gets through.
            return False
        team = team_view.team
        if team.parent_team_id is None or team.parent_team_id == team.id or team.parent_team is None:
            return True
        authenticator = request.successful_authenticator
        scoped_teams = None
        if isinstance(authenticator, OAuthAccessTokenAuthentication):
            scoped_teams = authenticator.access_token.scoped_teams
        elif isinstance(authenticator, PersonalAPIKeyAuthentication):
            scoped_teams = authenticator.personal_api_key.scoped_teams
        if scoped_teams and team.parent_team_id not in scoped_teams:
            return False
        level = team_view.user_permissions.team(team.parent_team).effective_membership_level
        return level is not None
