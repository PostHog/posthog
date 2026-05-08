from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class ObservationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class ObservationTrigger(models.TextChoices):
    SCHEDULE = "schedule", "Schedule"
    ON_DEMAND = "on_demand", "On demand"


class ReplayLensObservation(UUIDModel):
    """One application of a `ReplayLens` to a session recording (see README)."""

    lens = models.ForeignKey("replay_vision.ReplayLens", on_delete=models.CASCADE, related_name="observations")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    session_id = models.CharField(max_length=200, help_text="Session recording id this lens was applied to.")

    status = models.CharField(max_length=16, choices=ObservationStatus.choices, default=ObservationStatus.PENDING)
    error_reason = models.TextField(
        blank=True,
        default="",
        help_text="Populated on `status='failed'`. Includes the malformed model response on validation failure.",
    )
    workflow_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Temporal workflow id; used for progress queries and reaper reconciliation.",
    )

    lens_version = models.PositiveIntegerField(
        help_text="The `ReplayLens.lens_version` value at the time this observation ran."
    )
    lens_config_snapshot = models.JSONField(
        default=dict,
        help_text="`lens_config` as it was at run time. Edits to the lens don't retro-mutate this observation.",
    )

    model_used = models.CharField(max_length=64, blank=True, default="")
    provider_used = models.CharField(max_length=32, blank=True, default="")

    triggered_by = models.CharField(
        max_length=16,
        choices=ObservationTrigger.choices,
        help_text="What started this observation: a per-lens schedule fire or an explicit /observe/ call.",
    )
    triggered_by_user = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Populated for on-demand triggers; null for schedule-driven observations.",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # At-most-once: failed/succeeded rows are sticky; admin deletes to re-trigger.
            models.UniqueConstraint(fields=["lens", "session_id"], name="replay_lens_observation_unique_lens_session"),
            # Terminal status ⇔ completed_at non-null.
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=["pending", "running"], completed_at__isnull=True)
                    | models.Q(status__in=["succeeded", "failed"], completed_at__isnull=False)
                ),
                name="replay_lens_observation_completed_at_matches_status",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "created_at"], name="rlo_team_created_idx"),
            models.Index(fields=["lens", "status"], name="rlo_lens_status_idx"),
            # Partial index for the reaper's workflow_id lookups; excludes pending rows.
            models.Index(
                fields=["workflow_id"],
                name="rlo_workflow_id_idx",
                condition=~models.Q(workflow_id=""),
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        # Tenant invariant: observation.team_id must equal lens.team_id; validated only on create.
        if self._state.adding:
            lens_team_id = self.lens.team_id
            if self.team_id and self.team_id != lens_team_id:
                raise ValueError(
                    f"ReplayLensObservation.team_id ({self.team_id}) must match lens.team_id ({lens_team_id})"
                )
            self.team_id = lens_team_id
        super().save(*args, **kwargs)

    def mark_succeeded(self) -> None:
        """Transition to terminal `succeeded` while satisfying the completed_at invariant."""
        self.status = ObservationStatus.SUCCEEDED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    def mark_failed(self, error_reason: str) -> None:
        """Transition to terminal `failed` with a non-empty reason while satisfying the completed_at invariant."""
        self.status = ObservationStatus.FAILED
        self.error_reason = error_reason
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "error_reason"])

    def __str__(self) -> str:
        return f"{self.lens_id}:{self.session_id} [{self.status}]"
