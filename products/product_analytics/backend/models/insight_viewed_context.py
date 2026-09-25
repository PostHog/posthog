from django.conf import settings
from django.db import models


class InsightViewedContext(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False
    )
    insight = models.ForeignKey("product_analytics.Insight", on_delete=models.CASCADE, related_name="view_contexts")
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE, null=True, blank=True)
    source = models.CharField(max_length=64)
    last_viewed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "insight", "user", "source"],
                condition=models.Q(user__isnull=False, dashboard__isnull=True),
                name="ivc_user_standalone_unique",
            ),
            models.UniqueConstraint(
                fields=["team", "insight", "user", "source", "dashboard"],
                condition=models.Q(user__isnull=False, dashboard__isnull=False),
                name="ivc_user_dashboard_unique",
            ),
            models.UniqueConstraint(
                fields=["team", "insight", "source"],
                condition=models.Q(user__isnull=True, dashboard__isnull=True),
                name="ivc_anon_standalone_unique",
            ),
            models.UniqueConstraint(
                fields=["team", "insight", "source", "dashboard"],
                condition=models.Q(user__isnull=True, dashboard__isnull=False),
                name="ivc_anon_dashboard_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "insight", "-last_viewed_at"], name="ivc_insight_viewed_idx"),
            models.Index(fields=["team", "last_viewed_at"], name="ivc_team_viewed_idx"),
        ]
