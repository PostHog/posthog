from rest_framework.request import Request

from posthog.models import Team, User
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl


def may_read_reports(*, user: User, team: Team) -> bool:
    return UserAccessControl(user=user, team=team).check_access_level_for_resource("task", "viewer")


def credential_may_start_tasks(request: Request) -> bool:
    """Whether the request's credential may start a task run, as `task:write` allows.

    An inbox write can make a report qualify for auto-start, and the run then acts as the caller. A key
    or token that holds `inbox:write` without `task:write` must not reach a task run that way. Session
    auth has no scopes, so team membership and access control gate it instead.
    """
    scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    return scopes is None or "*" in scopes or not scopes_not_covered(scopes, ["task:write"])
