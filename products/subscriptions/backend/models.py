from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ProactiveSubscriptionConfig(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    subscription_id = models.BigIntegerField()
    enabled = models.BooleanField(default=False)
    allow_public_web_research = models.BooleanField(default=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team", "subscription_id"], name="proactive_config_team_subscription")
        ]


class ProactiveRecommendationRun(TeamScopedRootMixin, UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    subscription_id = models.BigIntegerField()
    delivery_id = models.UUIDField()
    actor_id = models.BigIntegerField()
    snapshot_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    failure_code = models.CharField(max_length=128, null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["team", "delivery_id"], name="proactive_run_team_delivery")]


class ProactiveRecommendation(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    run = models.ForeignKey(ProactiveRecommendationRun, on_delete=models.CASCADE, related_name="recommendations")
    semantic_key = models.CharField(max_length=128)
    recommendation = models.JSONField()
    citations = models.JSONField(default=list)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["run", "semantic_key"], name="proactive_recommendation_run_key")]
        indexes = [models.Index(fields=["team", "semantic_key", "created_at"])]
