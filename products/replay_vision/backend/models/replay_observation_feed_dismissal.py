from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class FeedDismissalReason(models.TextChoices):
    NOT_A_REAL_PROBLEM = "not_a_real_problem", "Not a real problem"
    ALREADY_KNOWN = "already_known", "Already known"
    NOT_MY_AREA = "not_my_area", "Not my area"
    OTHER = "other", "Other"


class ReplayObservationFeedDismissal(TeamScopedRootMixin, UUIDModel):
    """One user marked this observation not useful in What to watch. Per user, like `ReplayObservationView`."""

    # The unique constraint leads with observation_id, so a separate index on it would only slow writes.
    observation = models.ForeignKey(
        "replay_vision.ReplayObservation", on_delete=models.CASCADE, related_name="feed_dismissals", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    reason = models.CharField(max_length=32, choices=FeedDismissalReason.choices, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["observation", "user"], name="unique_replay_observation_feed_dismissal_per_user"
            ),
        ]
