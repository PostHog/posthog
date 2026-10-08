from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SubscriptionContext(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    subscription = models.ForeignKey("Subscription", on_delete=models.CASCADE, related_name="contexts")
    dashboard = models.ForeignKey(
        "dashboards.Dashboard",
        on_delete=models.CASCADE,
        null=True,
        related_name="+",
    )
    insight = models.ForeignKey(
        "product_analytics.Insight",
        on_delete=models.CASCADE,
        null=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def has_target_for_team(self, team_id: int, *, include_deleted: bool) -> bool:
        if self.dashboard_id is not None:
            return (
                self.dashboard is not None
                and self.dashboard.team_id == team_id
                and (include_deleted or not self.dashboard.deleted)
            )
        if self.insight_id is not None:
            return (
                self.insight is not None
                and self.insight.team_id == team_id
                and (include_deleted or not self.insight.deleted)
            )
        return False

    def has_live_target_for_team(self, team_id: int) -> bool:
        return self.has_target_for_team(team_id, include_deleted=False)

    def clean(self) -> None:
        super().clean()
        context_team_id = self.team.parent_team_id or self.team_id
        if self.subscription_id:
            subscription_team = self.subscription.team
            subscription_team_id = subscription_team.parent_team_id or subscription_team.id
            if subscription_team_id != context_team_id:
                raise ValidationError("Subscription context must belong to the subscription team.")
        target = self.dashboard if self.dashboard_id is not None else self.insight
        if target is not None and target.team_id != context_team_id:
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
