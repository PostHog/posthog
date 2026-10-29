from django.db import models
from django.utils.timezone import now

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.web_analytics.backend.models.heatmap_saved import SavedHeatmap


class HeatmapScreenshotHistory(TeamScopedRootMixin, UUIDModel):
    class Status(models.TextChoices):
        OK = "ok", "Captured"
        PENDING = "pending", "Capture pending"
        FAILED = "failed", "Capture failed"

    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", "Daily capture"
        MANUAL = "manual", "Requested capture"

    class ImageVariant(models.TextChoices):
        FULL = "full", "Full page"
        THUMBNAIL = "thumbnail", "Thumbnail"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    heatmap = models.ForeignKey(SavedHeatmap, on_delete=models.CASCADE, related_name="screenshot_history")
    width = models.IntegerField()
    captured_on = models.DateField()
    captured_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=100)
    day_start = models.DateTimeField()
    day_end = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    revision = models.UUIDField(null=True, blank=True)
    has_thumbnail = models.BooleanField(default=False)
    trigger = models.CharField(max_length=20, choices=Trigger, default=Trigger.SCHEDULED)
    status = models.CharField(max_length=20, choices=Status)
    failure_cause = models.CharField(max_length=100, null=True, blank=True)
    page_status = models.IntegerField(null=True, blank=True)
    latest_request = models.ForeignKey(
        "web_analytics.HeatmapCaptureRequest", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_heatmapscreenshothistory"
        constraints = [
            models.UniqueConstraint(fields=["heatmap", "captured_on"], name="heatmap_history_one_per_day"),
        ]

    @property
    def has_content(self) -> bool:
        return self.revision is not None


class HeatmapCaptureRequest(TeamScopedRootMixin, UUIDModel):
    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    LIVE_STATES = (State.QUEUED, State.RUNNING)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    heatmap = models.ForeignKey(SavedHeatmap, on_delete=models.CASCADE, related_name="history_requests")
    history = models.ForeignKey(HeatmapScreenshotHistory, on_delete=models.CASCADE, related_name="requests")
    state = models.CharField(max_length=16, choices=State, default=State.QUEUED)
    trigger = models.CharField(max_length=20, choices=HeatmapScreenshotHistory.Trigger)
    captured_on = models.DateField()
    timezone = models.CharField(max_length=100)
    day_start = models.DateTimeField()
    day_end = models.DateTimeField()
    width = models.PositiveIntegerField()
    url = models.URLField(max_length=2000)
    block_consent_modals = models.BooleanField()
    input_signature = models.CharField(max_length=64)
    claim_id = models.UUIDField(null=True)
    deadline = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    failure_cause = models.CharField(max_length=100, null=True)
    page_status = models.IntegerField(null=True)
    created_at = models.DateTimeField(default=now)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "posthog_heatmapcapturerequest"
        constraints = [
            models.UniqueConstraint(
                fields=["heatmap", "captured_on"],
                condition=models.Q(trigger="scheduled"),
                name="heatmap_history_one_scheduled",
            ),
        ]
        indexes = [
            models.Index(fields=["trigger", "created_at"], name="heatmap_request_global_idx"),
            models.Index(fields=["team", "captured_on", "trigger"], name="heatmap_request_team_idx"),
            models.Index(
                fields=["deadline"],
                condition=models.Q(state__in=["queued", "running"]),
                name="heatmap_request_live_idx",
            ),
        ]
