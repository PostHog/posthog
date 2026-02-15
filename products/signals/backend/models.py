from django.db import models

from posthog.models.utils import UUIDModel


class SignalReport(UUIDModel):
    class Status(models.TextChoices):
        POTENTIAL = "potential"
        CANDIDATE = "candidate"
        IN_PROGRESS = "in_progress"
        READY = "ready"
        FAILED = "failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POTENTIAL)

    total_weight = models.FloatField(default=0.0)
    signal_count = models.IntegerField(default=0)

    conversation = models.ForeignKey("ee.Conversation", null=True, blank=True, on_delete=models.SET_NULL)
    signals_at_run = models.IntegerField(default=0)

    # LLM-generated during signal matching
    title = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    relevant_user_count = models.IntegerField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "status", "promoted_at"]),
            models.Index(fields=["team", "created_at"]),
        ]


class SignalReportArtefact(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100)
    content = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)
