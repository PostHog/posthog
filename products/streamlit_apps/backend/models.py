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

    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("team", "short_id")

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

    has_requirements = models.BooleanField(default=False)
    packages = models.JSONField(default=list)

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
    version = models.ForeignKey(StreamlitAppVersion, on_delete=models.CASCADE)

    sandbox_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTING)

    restart_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    current_viewers = models.PositiveIntegerField(default=0)
    max_viewers = models.PositiveIntegerField(default=20)

    def __str__(self) -> str:
        return f"{self.app.name} sandbox ({self.status})"


class AllowedStreamlitPackage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    version_constraint = models.CharField(max_length=100, blank=True, default="")
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self) -> str:
        if self.version_constraint:
            return f"{self.name}{self.version_constraint}"
        return self.name
