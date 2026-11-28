from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import get_authenticator_scoped_team_ids, scopes_caller_lacks

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
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
    return may_read_reports(user=view.request.user, team=team) and authorization.check(
        resource=Resource(type=ResourceType.SIGNAL_SCOUT, project_id=team.pk),
        action=Action.VIEW,
        subject=Subject(user_id=view.request.user.pk),
    )
