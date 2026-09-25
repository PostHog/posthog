from django.db import models


class InsightQueryDemand(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    insight = models.ForeignKey("product_analytics.Insight", on_delete=models.CASCADE, related_name="query_demands")
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE, null=True, blank=True)
    last_requested_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "insight"],
                condition=models.Q(dashboard__isnull=True),
                name="insight_demand_standalone_unique",
            ),
            models.UniqueConstraint(
                fields=["team", "insight", "dashboard"],
                condition=models.Q(dashboard__isnull=False),
                name="insight_demand_dashboard_unique",
            ),
        ]
        indexes = [models.Index(fields=["last_requested_at"], name="insight_demand_requested_idx")]
