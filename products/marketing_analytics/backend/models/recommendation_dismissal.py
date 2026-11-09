from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.schema_enums import MarketingAnalyticsRecommendationRule

# Built from the query schema enum so a new rule needs no second list. The name also names the OpenAPI enum.
RecommendationRule = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "RecommendationRule", [(rule.name, rule.value) for rule in MarketingAnalyticsRecommendationRule]
)


def recommendation_rule_choices() -> list[tuple[str, str]]:
    return RecommendationRule.choices


class RecommendationDismissal(TeamScopedRootMixin, UUIDModel):
    # The unique constraint leads with team, so it serves team lookups.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    rule = models.CharField(max_length=64, choices=recommendation_rule_choices)
    subject = models.CharField(max_length=400)
    campaign = models.CharField(max_length=400, blank=True, default="")
    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "rule", "subject", "campaign"], name="ma_recommendation_dismissal_unique"
            )
        ]
