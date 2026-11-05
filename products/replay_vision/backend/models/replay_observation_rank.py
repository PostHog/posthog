from django.db import models
from django.db.models.functions import Now

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class RankCategory(models.IntegerChoices):
    FAILURE = 1, "Failure"
    STRUGGLE = 2, "Struggle"
    REVENUE = 3, "Revenue"
    ROUTINE = 4, "Routine"


class ReplayObservationRank(TeamScopedRootMixin, models.Model):
    """An observation's highlight rank, kept apart from the wide observation row so the feed reads only what ranking
    needs. A row is written once, when the observation is ranked under the current anchors."""

    # No database constraint, so the recording delete, which removes observations in raw SQL, never fails on a row here.
    observation = models.OneToOneField(
        "replay_vision.ReplayObservation",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="+",
        db_constraint=False,
    )
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False, db_index=False
    )
    # The observation's own cascade removes the row, so deleting a scanner does not scan this table for it.
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner",
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_constraint=False,
        db_index=False,
    )
    # The observation's own creation time, so a window filter never reads the observation row.
    created_at = models.DateTimeField()
    # Ranks from another anchor set do not compare, so readers ignore rows written under another version.
    anchor_version = models.PositiveSmallIntegerField()
    contrast = models.FloatField()
    category = models.PositiveSmallIntegerField(choices=RankCategory.choices)
    feed_group_id = models.UUIDField(null=True, blank=True)
    search_theme_id = models.UUIDField(null=True, blank=True)
    # A stable hash of the observation's person, or of its session when it has no person, so group reach counts
    # people without reading the observation.
    person_key = models.BigIntegerField()
    # The experiment the observation was scanned for, or 0, so readers can keep experiment-scoped rows to the viewers
    # allowed to read them.
    experiment_id = models.IntegerField(default=0)
    # When the rank was written, so a load can leave out rows ranked after its first page.
    ranked_at = models.DateTimeField(db_default=Now())

    class Meta:
        app_label = "replay_vision"
        indexes = [
            models.Index(
                fields=["team", "anchor_version", "created_at"],
                include=[
                    "observation",
                    "scanner",
                    "contrast",
                    "category",
                    "feed_group_id",
                    "person_key",
                    "experiment_id",
                ],
                name="rv_rank_team_window_idx",
            ),
            models.Index(
                fields=["feed_group_id"], name="rv_rank_feed_group_idx", condition=models.Q(feed_group_id__isnull=False)
            ),
            models.Index(
                fields=["search_theme_id", "created_at"],
                name="rv_rank_search_theme_idx",
                condition=models.Q(search_theme_id__isnull=False),
            ),
        ]
