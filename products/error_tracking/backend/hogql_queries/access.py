from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl


class ErrorTrackingQueryRunnerAccessMixin:
    team: Team

    def validate_query_runner_access(self, user: User) -> bool:
        UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("error_tracking", "viewer")
        return True
