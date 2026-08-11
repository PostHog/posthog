from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class BackfillStatus(models.TextChoices):
    RUNNING = "running", "Running"
    # Dispatch stopped because the org's monthly credit quota ran out; an explicit user resume restarts it.
    PAUSED_QUOTA = "paused_quota", "Paused (quota)"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


ACTIVE_BACKFILL_STATUSES = (BackfillStatus.RUNNING, BackfillStatus.PAUSED_QUOTA)


class ReplayScannerBackfill(TeamScopedRootMixin, UUIDModel):
    """One historical scan of a scanner over a closed time window (see README).

    The scanner's config is frozen into `scanner_snapshot` at creation, so the enumerated candidate
    set and the per-observation price never drift while the backfill runs — the cost quoted in the
    confirm dialog is an exact ceiling for the backfill's whole lifetime.
    """

    scanner = models.ForeignKey("replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="backfills")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    window_start = models.DateTimeField(help_text="Inclusive lower bound of the historical window to scan.")
    window_end = models.DateTimeField(help_text="Exclusive upper bound of the window; clamped to now at creation.")

    status = models.CharField(max_length=16, choices=BackfillStatus.choices, default=BackfillStatus.RUNNING)

    scanner_snapshot = models.JSONField(
        help_text="Frozen scanner config at creation; see `temporal.types.BackfillScannerSnapshot`."
    )
    credits_per_observation = models.PositiveIntegerField(
        help_text="Per-observation credit price frozen at creation from the snapshot model."
    )

    # Descending keyset cursor: the next batch selects (end_time, session_id) < (cursor_end_time, cursor_session_id).
    # Null until the first batch dispatches; the walk starts from window_end.
    cursor_end_time = models.DateTimeField(null=True, blank=True)
    cursor_session_id = models.CharField(max_length=200, blank=True, default="")

    total_count = models.PositiveIntegerField(
        help_text="Unobserved candidates enumerated at creation; the ceiling is total_count x credits_per_observation."
    )
    dispatched_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Candidates the walk stepped over because this scanner had already tried them. Counted at creation "
            "but never dispatched, so progress and remaining spend both have to account for them."
        ),
    )

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(
        null=True, blank=True, help_text="When the backfill reached a terminal status (completed or cancelled)."
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scanner"],
                condition=models.Q(status__in=["running", "paused_quota"]),
                name="rvb_one_active_per_scanner",
            ),
            models.CheckConstraint(
                condition=models.Q(window_start__lt=models.F("window_end")), name="rvb_window_start_before_end"
            ),
        ]
        indexes = [
            models.Index(fields=["team", "created_at"], name="rvb_team_created_idx"),
        ]

    def save(self, *args, **kwargs) -> None:
        # Tenant invariant: backfill.team_id must match scanner.team_id.
        if self._state.adding:
            scanner_team_id = self.scanner.team_id
            if self.team_id and self.team_id != scanner_team_id:
                raise ValueError(
                    f"ReplayScannerBackfill.team_id ({self.team_id}) must match scanner.team_id ({scanner_team_id})"
                )
            self.team_id = scanner_team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.scanner_id}:{self.window_start:%Y-%m-%d}..{self.window_end:%Y-%m-%d} [{self.status}]"
