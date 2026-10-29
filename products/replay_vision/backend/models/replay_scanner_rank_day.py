from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class ReplayScannerRankDay(TeamScopedRootMixin, models.Model):
    """A scanner's observations ranked under one anchor version on one UTC day, so the feed can turn a row's place
    into a percentile without counting every ranked row in the window."""

    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="rank_days", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    anchor_version = models.PositiveSmallIntegerField()
    day = models.DateField()
    observation_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "replay_vision"
        constraints = [
            models.UniqueConstraint(fields=["scanner", "anchor_version", "day"], name="rv_scanner_rank_day_unique")
        ]
