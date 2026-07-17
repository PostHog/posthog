from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class WebAnalyticsUserConfig(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False)
    achievements_opt_out = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_webanalyticsuserconfig"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="unique_web_analytics_user_config",
            ),
        ]
