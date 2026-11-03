from django.conf import settings
from django.db import models

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.utils import UUIDModel


class ConversionRecommendationRun(UUIDModel):
    objects = EnvironmentScopedManager()

    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    lookback_days = models.PositiveSmallIntegerField()
    date_from = models.DateTimeField()
    date_to = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)
    results = models.JSONField(default=dict)
    error = models.CharField(max_length=400, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team", "-created_at"], name="ma_conversion_run_recent")]
