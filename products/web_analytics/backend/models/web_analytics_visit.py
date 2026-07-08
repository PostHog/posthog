from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class WebAnalyticsVisit(TeamScopedRootMixin, UUIDModel):
    """One row per user per team-local calendar day they opened Web analytics. Single source of
    truth for streak and cumulative-loyalty achievements. `visit_date` is the team-local date, not
    a datetime — streak math must use the same team timezone that wrote it."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE)
    visit_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_webanalyticsvisit"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "visit_date"],
                name="unique_web_analytics_visit_per_day",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "user", "visit_date"], name="wa_visit_team_user_date_idx"),
        ]
