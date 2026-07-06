from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class WebAnalyticsAchievementProgress(TeamScopedRootMixin, UUIDModel):
    """Per-track achievement progress for a scope holder. `user` is NULL for team-scoped tracks
    (Conversions, Traffic) — never sum per-user rows into team totals. `state` holds the JSON
    detail: `unlocked_stages` (stage -> ISO timestamp), `pending_celebrations` (stages awaiting a
    client acknowledge), and `streak` (`last_visit_date`, `grace_used`)."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, null=True, blank=True)
    track_key = models.CharField(max_length=64)
    current_stage = models.PositiveSmallIntegerField(default=0)
    progress_value = models.BigIntegerField(default=0)
    state = models.JSONField(default=dict)
    last_computed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_webanalyticsachievementprogress"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "track_key"],
                condition=Q(user__isnull=False),
                name="unique_user_track_progress",
            ),
            models.UniqueConstraint(
                fields=["team", "track_key"],
                condition=Q(user__isnull=True),
                name="unique_team_track_progress",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "user"], name="wa_ach_team_user_idx"),
        ]
