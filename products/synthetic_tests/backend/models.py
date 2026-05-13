"""Django models for synthetic_tests."""

from django.db import models

from posthog.models.utils import UUIDTModel


class SyntheticTest(UUIDTModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"

    class Frequency(models.TextChoices):
        EVERY_5_MIN = "*/5 * * * *", "Every 5 minutes"
        EVERY_15_MIN = "*/15 * * * *", "Every 15 minutes"
        HOURLY = "0 * * * *", "Every hour"
        DAILY = "0 0 * * *", "Every day"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="synthetic_tests")
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    target_url = models.URLField(max_length=2048)
    steps = models.JSONField(default=list)

    schedule_cron = models.CharField(max_length=100, default=Frequency.EVERY_15_MIN)
    timezone = models.CharField(max_length=64, default="UTC")
    status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)
    create_issue_on_failure = models.BooleanField(default=True)

    source_replay_id = models.CharField(max_length=255, null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_synthetictest"
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["next_run_at"], name="synth_test_next_run_idx"),
        ]


class SyntheticTestRun(UUIDTModel):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        TIMEOUT = "timeout", "Timeout"
        ERROR = "error", "Error"

    synthetic_test = models.ForeignKey(SyntheticTest, on_delete=models.CASCADE, related_name="runs")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.RUNNING)
    duration_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    error_step_index = models.IntegerField(null=True, blank=True)
    screenshot_url = models.URLField(max_length=2048, blank=True, default="")
    issue_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "posthog_synthetictestrun"
        indexes = [
            models.Index(fields=["synthetic_test", "-started_at"]),
        ]
