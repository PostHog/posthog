from datetime import timedelta

from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel


class HeatmapAnalysis(TeamScopedRootMixin, UUIDTModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"
        UNAVAILABLE = "unavailable", "Unavailable"

    ACTIVE_STATUSES = [Status.QUEUED, Status.PROCESSING]
    STALE_AFTER = timedelta(minutes=15)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, db_constraint=False)
    heatmap = models.ForeignKey("web_analytics.SavedHeatmap", on_delete=models.CASCADE, related_name="analyses")
    url = models.URLField(max_length=2000)
    date_from = models.DateTimeField()
    date_to = models.DateTimeField()
    viewport_width = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status, default=Status.QUEUED)
    sampled_recordings = models.PositiveIntegerField(default=0)
    excluded_recordings = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    representatives = models.JSONField(default=dict)
    filters = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["team", "heatmap", "-created_at"], name="heatmap_analysis_saved_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(status__in=["queued", "processing"]),
                name="one_active_heatmap_analysis",
            )
        ]

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @classmethod
    def expire_stale(cls, team_id: int) -> int:
        now = timezone.now()
        return (
            cls.objects.for_team(team_id)
            .filter(status__in=cls.ACTIVE_STATUSES, updated_at__lt=now - cls.STALE_AFTER)
            .update(status=cls.Status.FAILED, error="Analysis timed out. Try again.", updated_at=now)
        )


class HeatmapAnalysisRecording(TeamScopedRootMixin, UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    analysis = models.ForeignKey(HeatmapAnalysis, on_delete=models.CASCADE, related_name="recordings")
    session_id = models.CharField(max_length=200)
    asset = models.ForeignKey("exports.ExportedAsset", on_delete=models.CASCADE, related_name="heatmap_sources")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["analysis", "session_id"], name="heatmap_analysis_recording")]
        indexes = [models.Index(fields=["team", "session_id"], name="heatmap_analysis_source_idx")]
