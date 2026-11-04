from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class FeatureFlagRolloutPlan(TeamScopedRootMixin, UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        STOPPED = "stopped", "Stopped"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    feature_flag = models.ForeignKey(
        "feature_flags.FeatureFlag", on_delete=models.CASCADE, related_name="+", db_constraint=False
    )
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, related_name="+", db_constraint=False
    )
    condition_index = models.PositiveSmallIntegerField()
    percentages = ArrayField(models.PositiveSmallIntegerField())
    soak_hours = models.PositiveSmallIntegerField()
    health_checks = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    steps_applied = models.PositiveSmallIntegerField(default=0)
    next_check_at = models.DateTimeField(null=True, blank=True)
    expected_flag_version = models.IntegerField()
    task_id = models.UUIDField(null=True, blank=True)
    latest_run_id = models.UUIDField(null=True, blank=True)
    last_summary = models.TextField(blank=True, default="")
    stop_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["feature_flag"],
                condition=Q(status="active"),
                name="one_active_rollout_plan_per_flag",
            )
        ]
        indexes = [models.Index(fields=["team", "feature_flag", "-created_at"], name="flag_rollout_plan_flag_idx")]
