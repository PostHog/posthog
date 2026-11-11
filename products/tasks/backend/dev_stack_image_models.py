from django.db import models

from posthog.models.utils import UUIDModel


class DevStackImageTarget(UUIDModel):
    region = models.CharField(max_length=16)
    name = models.CharField(max_length=128)
    enabled = models.BooleanField(default=False)
    auto_refresh = models.BooleanField(default=True)
    observation_revision = models.PositiveBigIntegerField(default=0)
    generation = models.PositiveBigIntegerField(default=0)
    base_reference = models.TextField(default="")
    repository_sha = models.CharField(max_length=40, default="")
    recipe_sha = models.CharField(max_length=64, default="")
    request_key = models.CharField(max_length=128, default="")
    pending_request_key = models.CharField(max_length=128, default="")
    requested_at = models.DateTimeField(null=True)
    observed_at = models.DateTimeField(null=True)
    observation_error = models.CharField(max_length=256, default="")
    active_image_id = models.CharField(max_length=128, default="")
    active_agent_version = models.CharField(max_length=64, default="")
    active_generation = models.PositiveBigIntegerField(default=0)
    active_base_reference = models.TextField(default="")
    active_repository_sha = models.CharField(max_length=40, default="")
    active_recipe_sha = models.CharField(max_length=64, default="")
    activated_at = models.DateTimeField(null=True)
    attempt_id = models.UUIDField(null=True)
    next_retry_at = models.DateTimeField(null=True)
    blocked_reason = models.CharField(max_length=256, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["region", "name"], name="tasks_dev_stack_region_name")]


class DevStackImageAttempt(UUIDModel):
    class Status(models.TextChoices):
        QUEUED = "queued"
        BUILDING = "building"
        VERIFYING = "verifying"
        ACTIVE = "active"
        FAILED = "failed"
        SUPERSEDED = "superseded"

    target = models.ForeignKey(DevStackImageTarget, on_delete=models.PROTECT, related_name="attempts")
    generation = models.PositiveBigIntegerField()
    base_reference = models.TextField()
    repository_sha = models.CharField(max_length=40)
    recipe_sha = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    bake_started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    deadline_at = models.DateTimeField(null=True)
    owner = models.UUIDField(null=True)
    candidate_image_id = models.CharField(max_length=128, default="")
    verified_at = models.DateTimeField(null=True)
    workflow_run_id = models.CharField(max_length=128, default="")
    error = models.CharField(max_length=256, default="")

    class Meta:
        indexes = [models.Index(fields=["target", "bake_started_at"], name="tasks_dev_stack_started")]
