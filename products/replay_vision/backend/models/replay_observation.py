from django.db import models

from posthog.models.utils import UUIDModel

from products.replay_vision.backend.error_kinds import ERROR_REASON_HELP_TEXT


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
    """One application of a `ReplayScanner` to a session recording (see README).

    Recording-scoped scanners produce one observation per (scanner, session). Moments-scoped scanners produce
    one per moment — a coalesced window around focus-event occurrences — discriminated by `moment_key`.
    """

    scanner = models.ForeignKey("replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="observations")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    session_id = models.CharField(max_length=200, help_text="Session recording id this scanner was applied to.")
    distinct_id = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        help_text="Distinct id of the person in the recorded session (the subject), resolved from session metadata.",
    )
    recording_subject_email = models.TextField(
        null=True,
        blank=True,
        help_text="Email of the recording subject at scan time; denormalized so the list can filter and sort on it.",
    )
    session_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Start time of the recorded session; copied from session metadata so downstream steps don't re-query.",
    )

    moment_key = models.CharField(
        max_length=36,
        blank=True,
        default="",
        db_default="",
        help_text=(
            "Identity discriminator within (scanner, session): empty for whole-recording observations, "
            "the anchor event's uuid for moments."
        ),
    )
    moment_event_name = models.CharField(
        max_length=400,
        blank=True,
        default="",
        db_default="",
        help_text="Name of the anchor focus event; denormalized for list display. Empty for whole-recording observations.",
    )
    moment_event_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Capture timestamp of the anchor focus event; null for whole-recording observations.",
    )
    window_start_offset_s = models.FloatField(
        null=True,
        blank=True,
        help_text="Observed window start, seconds from recording start; resolved at scan time and clamped to the recording.",
    )
    window_end_offset_s = models.FloatField(
        null=True,
        blank=True,
        help_text="Observed window end, seconds from recording start; null (with start) for whole-recording observations.",
    )
    coalesced_event_count = models.PositiveIntegerField(
        default=0,
        db_default=0,
        help_text="Focus-event occurrences merged into this moment's window (1 = no merging); 0 for whole-recording observations.",
    )

    status = models.CharField(max_length=16, choices=ObservationStatus.choices, default=ObservationStatus.PENDING)
    error_reason = models.TextField(blank=True, default="", help_text=ERROR_REASON_HELP_TEXT)
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
            # Failed/succeeded rows are sticky; admin deletes to re-trigger. moment_key is "" for whole-recording
            # rows, so for those this is exactly the old (scanner, session_id) uniqueness.
            models.UniqueConstraint(
                fields=["scanner", "session_id", "moment_key"],
                name="replay_observation_unique_scanner_session_moment",
            ),
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
            # Serves the per-scanner list ordering and the prev/next-neighbor lookups (both order by created_at).
            models.Index(fields=["scanner", "created_at"], name="rlo_scanner_created_idx"),
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
