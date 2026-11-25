from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import get_authenticator_scoped_team_ids, scopes_caller_lacks

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.facade.api import may_read_reports
from products.signals.backend.facade.scout_access import has_canonical_team_access


def canonical_scout_access(view: TeamAndOrgViewSetMixin) -> bool:
    return has_canonical_team_access(
        view.team, view.user_permissions, get_authenticator_scoped_team_ids(view.request.successful_authenticator)
    )


def show_scouts(view: TeamAndOrgViewSetMixin) -> bool:
    if scopes_caller_lacks(view.request, ["signal_scout:read", "inbox:read"]) or not canonical_scout_access(view):
        return False
    team = view.team.parent_team or view.team
    return may_read_reports(user=view.request.user, team=team) and UserAccessControl(
        user=view.request.user, team=team
    ).check_access_level_for_resource("signal_scout", "viewer")
