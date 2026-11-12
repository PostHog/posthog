import hashlib
from typing import Any

from django.conf import settings
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.schema_enums import (
    MarketingAnalyticsRecommendationIdentitySourceType,
    MarketingAnalyticsRecommendationResolutionState,
    MarketingAnalyticsRecommendationRule,
)

# Built from the query schema enums so a new value needs no second list. The names also name the OpenAPI enums.
RecommendationRule = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "RecommendationRule", [(rule.name, rule.value) for rule in MarketingAnalyticsRecommendationRule]
)
RecommendationSourceType = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "RecommendationSourceType",
    [(source_type.name, source_type.value) for source_type in MarketingAnalyticsRecommendationIdentitySourceType],
)
RecommendationResolutionState = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "RecommendationResolutionState",
    [(state.name, state.value) for state in MarketingAnalyticsRecommendationResolutionState],
)


def recommendation_rule_choices() -> list[tuple[str, str]]:
    return RecommendationRule.choices


def recommendation_source_type_choices() -> list[tuple[str, str]]:
    return RecommendationSourceType.choices


def subject_hash(subject: str) -> str:
    return hashlib.sha256(subject.encode()).hexdigest()


class RecommendationResolution(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    activity_logging_on_delete = True

    # The unique constraint leads with team, so it serves team lookups.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    rule = models.CharField(max_length=64, choices=recommendation_rule_choices)
    source_type = models.CharField(max_length=32, choices=recommendation_source_type_choices)
    customer_id = models.CharField(max_length=64, blank=True, default="")
    campaign_id = models.CharField(max_length=64, blank=True, default="")
    subject = models.TextField(blank=True, default="")
    # A btree entry holds about 2.7 KB, so the unique constraint keys on this hash instead of a search term.
    subject_hash = models.CharField(max_length=64, editable=False)
    resolution = models.CharField(max_length=16, choices=RecommendationResolutionState.choices)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )
    resolved_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "rule", "source_type", "customer_id", "campaign_id", "subject_hash"],
                name="ma_recommendation_resolution_unique",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.subject_hash = subject_hash(self.subject)
        super().save(*args, **kwargs)
