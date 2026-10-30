from typing import cast

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import get_authenticator_user_credential

from products.signals.backend.facade.scout_access import CANONICAL_TEAM_ACCESS_DENIED_MESSAGE, has_canonical_team_access


class ScoutCanonicalTeamAccessPermission(BasePermission):
    """Authorize requests against the project that owns the scout data."""

    message = CANONICAL_TEAM_ACCESS_DENIED_MESSAGE

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_view = cast(TeamAndOrgViewSetMixin, view)
        if not request.user.is_authenticated:
            # Unreachable while `IsAuthenticated` runs ahead of this class, but deny rather than
            # allow, so this class can never be the reason an anonymous request gets through.
            return False
        credential = get_authenticator_user_credential(request.successful_authenticator)
        scoped_team_ids = credential.scoped_teams if credential is not None else None
        return has_canonical_team_access(team_view.team, team_view.user_permissions, scoped_team_ids)
