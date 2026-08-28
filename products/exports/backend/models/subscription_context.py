from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SubscriptionContext(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    subscription = models.ForeignKey("Subscription", on_delete=models.CASCADE, related_name="contexts")
    dashboard = models.ForeignKey(
        "dashboards.Dashboard",
        on_delete=models.CASCADE,
        null=True,
        related_name="subscription_contexts_as_dashboard",
    )
    insight = models.ForeignKey(
        "product_analytics.Insight",
        on_delete=models.CASCADE,
        null=True,
        related_name="subscription_contexts_as_insight",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_subscription_context"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(dashboard__isnull=False, insight__isnull=True) | Q(dashboard__isnull=True, insight__isnull=False)
                ),
                name="subscription_context_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["subscription", "dashboard"],
                condition=Q(dashboard__isnull=False),
                name="subscription_context_unique_dashboard",
            ),
            models.UniqueConstraint(
                fields=["subscription", "insight"],
                condition=Q(insight__isnull=False),
                name="subscription_context_unique_insight",
            ),
        ]
