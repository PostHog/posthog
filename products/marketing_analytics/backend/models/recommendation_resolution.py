from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.schema_enums import MarketingAnalyticsRecommendationResolutionState, MarketingAnalyticsRecommendationRule

# Built from the query schema enum so a new rule needs no second list. The name also names the OpenAPI enum.
RecommendationRule = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "RecommendationRule", [(rule.name, rule.value) for rule in MarketingAnalyticsRecommendationRule]
)


def recommendation_rule_choices() -> list[tuple[str, str]]:
    return RecommendationRule.choices


RecommendationResolutionState = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "RecommendationResolutionState",
    [(state.name, state.value) for state in MarketingAnalyticsRecommendationResolutionState],
)


class RecommendationResolution(TeamScopedRootMixin, UUIDModel):
    class SourceType(models.TextChoices):
        GOOGLE_ADS = "google_ads", "Google Ads"

    # The unique constraint leads with team, so it serves team lookups.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    rule = models.CharField(max_length=64, choices=recommendation_rule_choices)
    source_type = models.CharField(max_length=32, choices=SourceType.choices, default=SourceType.GOOGLE_ADS)
    customer_id = models.CharField(max_length=64, blank=True, default="")
    campaign_id = models.CharField(max_length=64, blank=True, default="")
    subject = models.CharField(max_length=1024, blank=True, default="")
    resolution = models.CharField(max_length=16, choices=RecommendationResolutionState.choices)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )
    resolved_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # What the recommendation said when someone resolved it, since the recommendation itself is recomputed on read.
    snapshot = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "rule", "source_type", "customer_id", "campaign_id", "subject"],
                name="ma_recommendation_resolution_unique",
            )
        ]
