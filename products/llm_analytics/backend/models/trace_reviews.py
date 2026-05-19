from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from posthog.models.team.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel

from .score_definitions import ScoreDefinition


class TraceReview(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    trace_id = models.CharField(max_length=255)
    reviewed_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    comment = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at", "id"]
        indexes = [
            models.Index(fields=["team", "trace_id"], name="llma_tr_rev_trace_idx"),
            models.Index(fields=["team", "-updated_at", "id"], name="llma_tr_rev_upd_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "trace_id"],
                condition=Q(deleted=False),
                name="llma_tr_rev_active_uniq",
            )
        ]


class TraceReviewScore(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    review = models.ForeignKey(TraceReview, on_delete=models.CASCADE, related_name="scores")
    definition = models.ForeignKey(ScoreDefinition, on_delete=models.CASCADE, related_name="trace_review_scores")
    definition_version = models.UUIDField()
    definition_version_number = models.PositiveIntegerField()
    definition_config = models.JSONField(default=dict)
    categorical_values = ArrayField(models.CharField(max_length=128), null=True, blank=True)
    numeric_value = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["definition__name", "id"]
        indexes = [
            models.Index(fields=["team", "definition"], name="llma_tr_score_def_idx"),
            models.Index(fields=["team", "review"], name="llma_tr_score_rev_idx"),
            GinIndex(fields=["categorical_values"], name="llma_tr_score_cat_gin"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["review", "definition"],
                name="llma_tr_score_def_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        Q(categorical_values__isnull=False)
                        & Q(numeric_value__isnull=True)
                        & Q(boolean_value__isnull=True)
                    )
                    | (
                        Q(categorical_values__isnull=True)
                        & Q(numeric_value__isnull=False)
                        & Q(boolean_value__isnull=True)
                    )
                    | (
                        Q(categorical_values__isnull=True)
                        & Q(numeric_value__isnull=True)
                        & Q(boolean_value__isnull=False)
                    )
                ),
                name="llma_tr_score_one_chk",
            ),
        ]
