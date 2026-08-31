from typing import Any

from django.core.exceptions import ValidationError
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

    def clean(self) -> None:
        super().clean()
        if self.subscription_id and self.subscription.team_id != self.team_id:
            raise ValidationError("Subscription context must belong to the subscription team.")
        target = self.dashboard if self.dashboard_id is not None else self.insight
        if target is not None and target.team_id != self.team_id:
            raise ValidationError("Subscription context target must belong to the context team.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

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
