from django.db import models
from django.db.models import Q

from posthog.models.team.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel


class TraceReview(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    class ScoreKind(models.TextChoices):
        LABEL = "label", "label"
        NUMERIC = "numeric", "numeric"

    class ScoreLabel(models.TextChoices):
        GOOD = "good", "good"
        BAD = "bad", "bad"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    trace_id = models.CharField(max_length=255)
    reviewed_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    score_kind = models.CharField(max_length=32, choices=ScoreKind.choices, null=True, blank=True)
    score_label = models.CharField(max_length=32, choices=ScoreLabel.choices, null=True, blank=True)
    score_numeric = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    comment = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at", "id"]
        indexes = [
            models.Index(fields=["team", "trace_id"]),
            models.Index(fields=["team", "-updated_at", "id"]),
            models.Index(fields=["team", "score_kind", "score_label"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "trace_id"],
                condition=Q(deleted=False),
                name="uniq_active_llma_trace_review_per_team",
            )
        ]
