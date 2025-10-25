from django.db import models
from django.utils import timezone

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel


class DesktopRecording(UUIDModel):
    class Status(models.TextChoices):
        RECORDING = "recording", "Recording"
        UPLOADING = "uploading", "Uploading"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        ERROR = "error", "Error"

    class Platform(models.TextChoices):
        ZOOM = "zoom", "Zoom"
        TEAMS = "teams", "Microsoft Teams"
        MEET = "meet", "Google Meet"
        DESKTOP_AUDIO = "desktop_audio", "Desktop audio"
        SLACK = "slack", "Slack huddle"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="desktop_recordings")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    sdk_upload_id = models.UUIDField(unique=True, db_index=True)
    recall_recording_id = models.UUIDField(null=True, blank=True, db_index=True)

    platform = models.CharField(max_length=20, choices=Platform.choices)
    meeting_title = models.CharField(max_length=255, null=True, blank=True)
    meeting_url = models.URLField(null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)
    participants = models.JSONField(default=list)

    video_url = models.URLField(null=True, blank=True)
    video_size_bytes = models.BigIntegerField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECORDING)
    notes = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_desktop_recording"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["team", "-started_at"]),
            models.Index(fields=["created_by", "-started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.meeting_title or 'Recording'} ({self.platform})"


class RecordingTranscript(models.Model):
    recording = models.OneToOneField(DesktopRecording, on_delete=models.CASCADE, related_name="transcript")

    full_text = models.TextField()
    segments = models.JSONField(default=list)

    summary = models.TextField(null=True, blank=True)
    extracted_tasks = models.JSONField(default=list)

    # AI processing timestamps
    tasks_generated_at = models.DateTimeField(null=True, blank=True)
    summary_generated_at = models.DateTimeField(null=True, blank=True)

    search_vector = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_recording_transcript"

    def __str__(self) -> str:
        return f"Transcript for {self.recording}"
