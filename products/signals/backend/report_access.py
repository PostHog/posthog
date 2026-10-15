from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl


def may_read_reports(*, user: User, team: Team) -> bool:
    return UserAccessControl(user=user, team=team).check_access_level_for_resource("task", "viewer")
