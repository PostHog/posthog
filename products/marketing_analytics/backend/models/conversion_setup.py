from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ConversionRecommendationRun(TeamScopedRootMixin, UUIDModel):
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


class ConversionGoalPreviewEvidence(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    goal = models.JSONField()
    context_hash = models.CharField(max_length=64)
    applied_goal = models.JSONField(null=True)

    class Meta:
        indexes = [models.Index(fields=["team", "expires_at"], name="ma_goal_preview_expiry")]
