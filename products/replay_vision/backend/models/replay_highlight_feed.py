from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class HighlightWindow(models.IntegerChoices):
    """The feed's preset windows, in days."""

    DAY = 1, "Last 24 hours"
    WEEK = 7, "Last 7 days"
    MONTH = 30, "Last 30 days"
    QUARTER = 90, "Last 90 days"


class ReplayHighlightFeedState(TeamScopedRootMixin, models.Model):
    """Which stored build of a team's highlight feed is current, and when the team's ranks last changed."""

    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, related_name="+", db_constraint=False
    )
    # The current build, as the epoch second it ranked to, so a page load can stay on the build its first page read.
    generation = models.PositiveIntegerField(default=0)
    built_at = models.DateTimeField(null=True, blank=True)
    # A rank written after the last build sets this, so a rebuild picks the team up.
    changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "replay_vision"


class ReplayHighlightFeedEntry(TeamScopedRootMixin, models.Model):
    """One ranked candidate of a team's highlight feed for one window, as of one build. A page load filters and
    orders these instead of ranking the window itself."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    window_days = models.PositiveSmallIntegerField(choices=HighlightWindow.choices)
    generation = models.PositiveIntegerField()
    # The row's place in its scanner by score in this window, best first.
    place = models.PositiveIntegerField()
    observation_id = models.UUIDField()
    scanner_id = models.UUIDField()
    created_at = models.DateTimeField()
    category = models.PositiveSmallIntegerField()
    experiment_id = models.IntegerField(default=0)
    percentile = models.FloatField()
    group_root = models.UUIDField()
    group_sessions = models.PositiveIntegerField()
    group_people = models.PositiveIntegerField()

    class Meta:
        app_label = "replay_vision"
        indexes = [
            models.Index(fields=["team", "generation", "window_days", "place"], name="rv_highlight_entry_read_idx"),
            models.Index(fields=["observation_id"], name="rv_highlight_entry_obs_idx"),
        ]
