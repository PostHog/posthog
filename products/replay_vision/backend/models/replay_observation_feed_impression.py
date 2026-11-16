from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ReplayObservationFeedImpression(TeamScopedRootMixin, UUIDModel):
    """How often Highlights showed this observation to one user, so the feed can rank it lower each time."""

    # The unique constraint leads with observation_id, so a separate index on it would only slow writes.
    observation = models.ForeignKey(
        "replay_vision.ReplayObservation", on_delete=models.CASCADE, related_name="feed_impressions", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    shown_count = models.PositiveIntegerField(default=1)
    last_shown_at = models.DateTimeField()
    # The feed load that last counted, so one load counts each card once however often it reports it.
    last_feed_load_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["observation", "user"], name="unique_replay_observation_feed_impression_per_user"
            ),
        ]
