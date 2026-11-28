from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class FlagWindowState(models.TextChoices):
    OPEN = "open", "Open"
    SUSPICIOUS = "suspicious", "Suspicious"
    CLOSED = "closed", "Closed"


class FlagObservationWindow(TeamScopedRootMixin, UUIDModel):
    """The watch over one flag edit that raised exposure, while it can still show a rise in errors.

    `flag_windows/window.py` decides what happens to the window. A flag has at most one window that is not closed: an
    edit that changes who gets which value closes it, and the next window watches that edit or what is left of this one.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE lock on posthog_team (a hot table)
    # while migrating. No standalone index: the indexes below lead on team.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    # Keeps its own index because a flag delete cascades here by feature_flag_id alone.
    feature_flag = models.ForeignKey(
        "feature_flags.FeatureFlag", on_delete=models.CASCADE, related_name="observation_windows"
    )
    # The activity log entry of the edit that the window watches. A bare UUID, so that the retention of the activity
    # log never deletes a window.
    activity_log_id = models.UUIDField(unique=True)
    edited_at = models.DateTimeField()
    # The fields of `FlagExposureConfig` that the window compares the flag with, and the ones that the edit set.
    config_before = models.JSONField()
    config_after = models.JSONField()
    # The window that this edit superseded, so the scoring can keep its baseline.
    previous_window = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    state = models.CharField(max_length=16, choices=FlagWindowState.choices, default=FlagWindowState.OPEN)
    close_reason = models.CharField(max_length=32, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["feature_flag"], condition=~Q(state="closed"), name="ff_obs_window_one_live_per_flag"
            ),
            models.CheckConstraint(
                condition=Q(state="closed", close_reason__isnull=False, closed_at__isnull=False)
                | (~Q(state="closed") & Q(close_reason__isnull=True, closed_at__isnull=True)),
                name="ff_obs_window_closed_has_reason",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "state"], name="ff_obs_window_team_state_idx"),
        ]

    def __str__(self) -> str:
        return f"FlagObservationWindow(team={self.team_id}, flag={self.feature_flag_id}, state={self.state})"


class FlagWindowsCursor(TeamScopedRootMixin):
    """How far the windows of a team read the activity log. Only the flag windows workflow writes it."""

    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    read_until = models.DateTimeField()

    def __str__(self) -> str:
        return f"FlagWindowsCursor(team={self.team_id}, read_until={self.read_until})"
