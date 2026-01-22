from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDTModel


class LLMAnalyticsAnnotation(UUIDTModel):
    """
    Structured review/feedback for LLM Analytics entities (traces, sessions, outputs, etc.).

    This is intentionally separate from posthog.models.annotation.Annotation, which is oriented around
    dashboards/insights/project/org annotations.
    """

    class TargetType(models.TextChoices):
        TRACE = "trace", "trace"
        SESSION = "session", "session"
        EXPERIMENT = "experiment", "experiment"
        GENERATION = "generation", "generation"
        OUTPUT = "output", "output"
        EVALUATION = "evaluation", "evaluation"
        DATASET_ITEM = "dataset_item", "dataset_item"

    class Meta:
        app_label = "llm_analytics"
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "target_type", "target_id"]),
            models.Index(fields=["team", "deleted", "-created_at"]),
        ]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, null=True, blank=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    # Human + structured feedback
    content = models.TextField(blank=True, default="")
    rating = models.IntegerField(null=True, blank=True)  # optional (e.g., 1–5); validated at API layer
    data = models.JSONField(default=dict, blank=True)  # arbitrary structured feedback

    # What this feedback is attached to
    target_type = models.CharField(max_length=64, choices=TargetType.choices)
    target_id = models.CharField(max_length=256)

    created_at = models.DateTimeField(default=timezone.now, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.target_type}:{self.target_id}"
