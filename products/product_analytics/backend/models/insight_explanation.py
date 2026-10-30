from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, sane_repr


class InsightExplanation(UUIDModel, TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    insight = models.ForeignKey(
        "product_analytics.Insight", on_delete=models.CASCADE, related_name="explanations", db_constraint=False
    )
    data = models.JSONField()
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("id", "insight_id")
