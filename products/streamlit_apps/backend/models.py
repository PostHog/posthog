import uuid

from django.db import models

from posthog.utils import generate_short_id


class StreamlitApp(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    active_version = models.ForeignKey(
        "StreamlitAppVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    cpu_cores = models.FloatField(default=0.5)
    memory_gb = models.FloatField(default=1)

    # Reset to zero on a healthy run so transient failures don't ratchet the cap.
    restart_count = models.PositiveIntegerField(default=0)

    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "short_id"],
                condition=models.Q(deleted=False),
                name="streamlit_apps_app_unique_active_short_id_per_team",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class StreamlitAppVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.ForeignKey(StreamlitApp, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()

    zip_file = models.CharField(max_length=500)
    zip_hash = models.CharField(max_length=64)

    snapshot_id = models.CharField(max_length=255, null=True, blank=True)
    snapshot_created_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("app", "version_number")
        ordering = ["-version_number"]

    def __str__(self) -> str:
        return f"{self.app.name} v{self.version_number}"


class StreamlitAppSandbox(models.Model):
    class Status(models.TextChoices):
        STARTING = "starting", "Starting"
        RUNNING = "running", "Running"
        STOPPING = "stopping", "Stopping"
        STOPPED = "stopped", "Stopped"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.OneToOneField(StreamlitApp, on_delete=models.CASCADE, related_name="sandbox")
    version = models.ForeignKey(StreamlitAppVersion, on_delete=models.SET_NULL, null=True, blank=True)

    sandbox_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTING)

    last_error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    # The row is reused in place across lifecycles, so this drifts. Use
    # started_at (refreshed on each attempt) for "this attempt began" logic.
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.app.name} sandbox ({self.status})"
