from typing import TYPE_CHECKING

from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl

if TYPE_CHECKING:
    from posthog.models.team.team import Team


class MarketingAnalyticsAccessMixin:
    """Every marketing analytics query runner requires viewer access to the `marketing_analytics` resource."""

    team: "Team"

    def validate_query_runner_access(self, user: User) -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        return user_access_control.assert_access_level_for_resource("marketing_analytics", "viewer")
