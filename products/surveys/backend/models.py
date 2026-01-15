from django.db import models

from posthog.models.utils import UUIDModel


class SurveyRecommendation(UUIDModel):
    class RecommendationType(models.TextChoices):
        LOW_CONVERSION_FUNNEL = "low_conversion_funnel", "Low conversion funnel"
        FEATURE_FLAG_FEEDBACK = "feature_flag_feedback", "Feature flag feedback"
        EXPERIMENT_FEEDBACK = "experiment_feedback", "Experiment feedback"
        DECLINING_FEATURE = "declining_feature", "Declining feature"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISMISSED = "dismissed", "Dismissed"
        CONVERTED = "converted", "Converted"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="survey_recommendations",
    )

    recommendation_type = models.CharField(
        max_length=50,
        choices=RecommendationType.choices,
    )

    survey_defaults = models.JSONField(
        help_text="JSON payload that can be used to create a survey via the API",
    )

    display_context = models.JSONField(
        help_text="Title, description, and metrics for rendering the recommendation card",
    )

    score = models.FloatField(default=0.0)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    source_insight = models.ForeignKey(
        "posthog.Insight",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="survey_recommendations",
    )
    source_feature_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="survey_recommendations",
    )
    source_experiment = models.ForeignKey(
        "posthog.Experiment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="survey_recommendations",
    )

    converted_survey = models.ForeignKey(
        "posthog.Survey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_recommendations",
    )

    class Meta:
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["team", "recommendation_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_insight"],
                condition=models.Q(source_insight__isnull=False, status="active"),
                name="unique_active_insight_recommendation",
            ),
            models.UniqueConstraint(
                fields=["team", "source_feature_flag"],
                condition=models.Q(source_feature_flag__isnull=False, status="active"),
                name="unique_active_flag_recommendation",
            ),
            models.UniqueConstraint(
                fields=["team", "source_experiment"],
                condition=models.Q(source_experiment__isnull=False, status="active"),
                name="unique_active_experiment_recommendation",
            ),
        ]

    def __str__(self):
        return f"SurveyRecommendation({self.recommendation_type}, score={self.score})"
