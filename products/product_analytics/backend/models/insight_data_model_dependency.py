from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class InsightDataModelDependency(TeamScopedRootMixin):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    insight = models.ForeignKey(
        "product_analytics.Insight",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    saved_query_id = models.UUIDField()
    query_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TeamScopedRootMixin.Meta):
        db_table = "posthog_insightdatamodeldependency"
        constraints = [
            models.UniqueConstraint(
                fields=("team", "insight", "saved_query_id"),
                name="insight_dmdep_team_ins_sq_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("team", "saved_query_id", "insight"),
                name="insight_dmdep_team_sq_ins_idx",
            )
        ]
