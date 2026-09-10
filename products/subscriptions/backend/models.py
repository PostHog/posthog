from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ProactiveSubscriptionConfig(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    subscription_id = models.BigIntegerField()
    enabled = models.BooleanField(default=False)
    allow_public_web_research = models.BooleanField(default=True)
    create_draft_pr = models.BooleanField(default=False)
    repository = models.CharField(max_length=201, null=True, blank=True)
    repository_integration_id = models.IntegerField(null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team", "subscription_id"], name="proactive_config_team_subscription")
        ]


class ProactiveRecommendationRun(TeamScopedRootMixin, UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    subscription_id = models.BigIntegerField()
    delivery_id = models.UUIDField()
    actor_id = models.BigIntegerField()
    snapshot_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    failure_code = models.CharField(max_length=128, null=True, blank=True)
    staged_run_id = models.UUIDField(null=True, blank=True)
    task_id = models.UUIDField(null=True, blank=True)
    analysis_run_id = models.UUIDField(null=True, blank=True)
    repository_binding = models.JSONField(null=True, blank=True)
    artifact_config_hash = models.CharField(max_length=64, null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["team", "delivery_id"], name="proactive_run_team_delivery")]


class ProactiveRecommendation(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    run = models.ForeignKey(ProactiveRecommendationRun, on_delete=models.CASCADE, related_name="recommendations")
    semantic_key = models.CharField(max_length=128)
    recommendation = models.JSONField()
    citations = models.JSONField(default=list)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["run", "semantic_key"], name="proactive_recommendation_run_key")]
        indexes = [models.Index(fields=["team", "semantic_key", "created_at"])]


class ProactivePreparedArtifact(TeamScopedRootMixin, UUIDModel):
    class Kind(models.TextChoices):
        DRAFT_PR = "draft_pr", "Draft pull request"
        EXPERIMENT_DRAFT = "experiment_draft", "Experiment draft"

    class Status(models.TextChoices):
        PREPARING = "preparing", "Preparing"
        PREPARED = "prepared", "Prepared"
        ADOPTED = "adopted", "Adopted"
        FAILED = "failed", "Failed"

    class AdoptionSource(models.TextChoices):
        DRAFT_PR_MERGED = "draft_pr_merged", "Draft pull request merged"
        EXPERIMENT_ACTIVATED = "experiment_activated", "Experiment activated"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    run = models.OneToOneField(ProactiveRecommendationRun, on_delete=models.CASCADE, related_name="prepared_artifact")
    recommendation = models.OneToOneField(
        ProactiveRecommendation, on_delete=models.CASCADE, related_name="prepared_artifact"
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PREPARING)
    artifact_config_hash = models.CharField(max_length=64)
    input_hash = models.CharField(max_length=64)
    task_publication_id = models.UUIDField(null=True, blank=True)
    staged_run_id = models.UUIDField(null=True, blank=True)
    experiment_id = models.IntegerField(null=True, blank=True)
    feature_flag_id = models.IntegerField(null=True, blank=True)
    prior_artifact = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="subsequent_artifacts"
    )
    url = models.URLField(max_length=2_000, null=True, blank=True)
    failure_code = models.CharField(max_length=128, null=True, blank=True)
    prepared_at = models.DateTimeField(null=True, blank=True)
    adoption_source = models.CharField(max_length=32, choices=AdoptionSource.choices, null=True, blank=True)
    adopted_at = models.DateTimeField(null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        indexes = [
            models.Index(fields=["team", "status", "created_at"]),
            models.Index(
                fields=["updated_at", "id"],
                condition=models.Q(adopted_at__isnull=True),
                name="subs_artifact_reconcile_idx",
            ),
        ]


class ProactiveRecommendationOutcome(TeamScopedRootMixin, UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IMPROVED = "improved", "Improved"
        REGRESSED = "regressed", "Regressed"
        INCONCLUSIVE = "inconclusive", "Inconclusive"
        UNAVAILABLE = "unavailable", "Unavailable"

    class Direction(models.TextChoices):
        INCREASE = "increase", "Increase"
        DECREASE = "decrease", "Decrease"

    class FailureCode(models.TextChoices):
        BASELINE_UNAVAILABLE = "baseline_unavailable", "Baseline unavailable"
        INSIGHT_NOT_FOUND = "insight_not_found", "Insight not found"
        INSIGHT_AUTHORITY_CHANGED = "insight_authority_changed", "Insight authority changed"
        QUERY_ERROR = "query_error", "Query error"
        RESPONSE_UNSUPPORTED = "response_unsupported", "Response unsupported"
        ZERO_BASELINE = "zero_baseline", "Zero baseline"
        FLAT_MOVEMENT = "flat_movement", "Flat movement"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    artifact = models.OneToOneField(ProactivePreparedArtifact, on_delete=models.CASCADE, related_name="outcome")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    measurement_spec = models.JSONField(null=True, blank=True)
    metric_name = models.CharField(max_length=300, null=True, blank=True)
    expected_metric_movement = models.CharField(max_length=1000, null=True, blank=True)
    direction = models.CharField(max_length=16, choices=Direction.choices, null=True, blank=True)
    baseline_value = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    observed_value = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    delta = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    baseline_from = models.DateField(null=True, blank=True)
    baseline_to = models.DateField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    observed_from = models.DateTimeField(null=True, blank=True)
    observed_to = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=128, choices=FailureCode.choices, null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        indexes = [
            models.Index(fields=["due_at"]),
            models.Index(
                fields=["updated_at", "id"],
                condition=models.Q(status="pending", due_at__isnull=False),
                name="subs_outcome_dispatch_idx",
            ),
        ]
