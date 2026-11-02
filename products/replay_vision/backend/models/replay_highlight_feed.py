from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class HighlightWindow(models.IntegerChoices):
    """The feed's preset windows, in days."""

    DAY = 1, "Last 24 hours"
    WEEK = 7, "Last 7 days"
    MONTH = 30, "Last 30 days"
    QUARTER = 90, "Last 90 days"


class ReplayHighlightFeedState(TeamScopedRootMixin, models.Model):
    """Which stored build of a team's highlight feed is current, and whether ranks changed since it was built."""

    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, related_name="+", db_constraint=False
    )
    generation = models.PositiveBigIntegerField(default=0)
    built_at = models.DateTimeField(null=True, blank=True)
    # Each kept build as `[generation, ISO time it became current]`, so a load stays on the build its first page read.
    builds = models.JSONField(default=list)
    # Counts asks for a rebuild; a build records the count it saw, so an ask that lands during a build is not lost.
    changes = models.PositiveBigIntegerField(default=0)
    built_changes = models.PositiveBigIntegerField(default=0)
    # The last time a sweep tried to build the team, so a team whose builds keep failing waits its turn.
    attempted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "replay_vision"


class ReplayHighlightFeedEntry(TeamScopedRootMixin, models.Model):
    """One ranked candidate of a team's highlight feed for one window, as of one build. A page load filters and
    orders these instead of ranking the window itself."""

    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False, db_index=False
    )
    window_days = models.PositiveSmallIntegerField(choices=HighlightWindow.choices)
    generation = models.PositiveBigIntegerField()
    # The row's place in its scanner by score in this window, best first.
    place = models.PositiveIntegerField()
    observation_id = models.UUIDField()
    scanner_id = models.UUIDField()
    created_at = models.DateTimeField()
    category = models.PositiveSmallIntegerField()
    experiment_id = models.IntegerField(default=0)
    percentile = models.FloatField()
    group_root = models.UUIDField()
    # Spaces one person's cards apart without reading the observations.
    person_key = models.BigIntegerField(null=True)

    class Meta:
        app_label = "replay_vision"
        indexes = [
            models.Index(fields=["team", "generation", "window_days", "place"], name="rv_highlight_entry_read_idx"),
            models.Index(fields=["observation_id"], name="rv_highlight_entry_obs_idx"),
        ]
