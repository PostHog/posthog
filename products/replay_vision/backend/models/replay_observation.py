from django.db import models

from posthog.models.utils import UUIDModel


class ObservationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    # Terminal state for sessions the scanner can't analyze (no recording, too short, too long, etc.).
    # The reason kind is stored in `error_reason` formatted as `kind:human message`.
    INELIGIBLE = "ineligible", "Ineligible"


class ObservationTrigger(models.TextChoices):
    SCHEDULE = "schedule", "Schedule"
    ON_DEMAND = "on_demand", "On demand"


class ReplayObservation(UUIDModel):
    """One application of a `ReplayScanner` to a session recording (see README)."""

    scanner = models.ForeignKey("replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="observations")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    session_id = models.CharField(max_length=200, help_text="Session recording id this scanner was applied to.")

    status = models.CharField(max_length=16, choices=ObservationStatus.choices, default=ObservationStatus.PENDING)
    error_reason = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Populated on terminal non-success statuses; formatted as `kind:human-readable message`. "
            "For `ineligible`, kind is one of no_recording / too_short / too_inactive / too_long / no_events. "
            "For `failed`, kind is one of provider_transient / provider_rejected / rasterization_failed / "
            "validation_failed / internal_error."
        ),
    )
    workflow_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Temporal workflow id; used for progress queries and reaper reconciliation.",
    )

    scanner_snapshot = models.JSONField(
        default=dict,
        help_text="Frozen view of the scanner at observation-create time; see `temporal.types.ScannerSnapshot`.",
    )
    scanner_result = models.JSONField(
        default=dict,
        help_text="Result data persisted on success (model output, signals count); see `temporal.types.ScannerResult`.",
    )

    triggered_by = models.CharField(
        max_length=16,
        choices=ObservationTrigger.choices,
        help_text="What started this observation: a per-scanner schedule fire or an explicit /observe/ call.",
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
            # Failed/succeeded rows are sticky; admin deletes to re-trigger.
            models.UniqueConstraint(fields=["scanner", "session_id"], name="replay_observation_unique_scanner_session"),
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=["pending", "running"], completed_at__isnull=True)
                    | models.Q(status__in=["succeeded", "failed", "ineligible"], completed_at__isnull=False)
                ),
                name="replay_observation_completed_at_matches_status",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "created_at"], name="rlo_team_created_idx"),
            models.Index(fields=["scanner", "status"], name="rlo_scanner_status_idx"),
            models.Index(
                fields=["workflow_id"],
                name="rlo_workflow_id_idx",
                condition=~models.Q(workflow_id=""),
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        # Tenant invariant: observation.team_id must match scanner.team_id.
        if self._state.adding:
            scanner_team_id = self.scanner.team_id
            if self.team_id and self.team_id != scanner_team_id:
                raise ValueError(
                    f"ReplayObservation.team_id ({self.team_id}) must match scanner.team_id ({scanner_team_id})"
                )
            self.team_id = scanner_team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.scanner_id}:{self.session_id} [{self.status}]"
