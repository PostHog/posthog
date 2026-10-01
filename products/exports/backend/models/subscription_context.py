import sys
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    # Resolved lazily via __getattr__ below; declared here so consumers type-check as int.
    MAX_SELECTED_CONTEXTS: int
    MAX_CONTEXT_READ_BUDGET: int

_LAZY_INT_CONSTANTS = ("MAX_SELECTED_CONTEXTS", "MAX_CONTEXT_READ_BUDGET")


# Single source of truth shared with the frontend via generated schema
# (SubscriptionAIContextSelectionLimit / SubscriptionAIContextReadBudget). Resolved lazily
# via PEP 562 so posthog.schema (the pydantic models) stays off django.setup(), where this
# model loads in every process.
def __getattr__(name: str) -> int:
    if name in _LAZY_INT_CONSTANTS:
        from posthog.schema import SubscriptionAIContextReadBudget, SubscriptionAIContextSelectionLimit  # noqa: PLC0415

        globals()["MAX_SELECTED_CONTEXTS"] = int(SubscriptionAIContextSelectionLimit.model_fields["root"].default)
        globals()["MAX_CONTEXT_READ_BUDGET"] = int(SubscriptionAIContextReadBudget.model_fields["root"].default)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _max_selected_contexts() -> int:
    # Module-attribute lookup (not a direct global read) so tests patching
    # MAX_SELECTED_CONTEXTS on this module still take effect.
    return sys.modules[__name__].MAX_SELECTED_CONTEXTS


@frozen
class ReportContextSelection:
    dashboard_ids: tuple[int, ...] = ()
    insight_ids: tuple[int, ...] = ()
    over_limit: bool = False


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

    @classmethod
    def report_selection(cls, *, team_id: int, subscription_id: int) -> ReportContextSelection:
        max_selected_contexts = _max_selected_contexts()
        context_rows = list(
            cls.objects.for_team(team_id)
            .filter(subscription_id=subscription_id)
            .order_by("created_at", "id")
            .values_list("dashboard_id", "insight_id")[: max_selected_contexts + 1]
        )
        return ReportContextSelection(
            dashboard_ids=tuple(
                sorted(
                    dashboard_id for dashboard_id, _ in context_rows[:max_selected_contexts] if dashboard_id is not None
                )
            ),
            insight_ids=tuple(
                sorted(insight_id for _, insight_id in context_rows[:max_selected_contexts] if insight_id is not None)
            ),
            over_limit=len(context_rows) > max_selected_contexts,
        )

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
