from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ReplayObservationView(TeamScopedRootMixin, UUIDModel):
    """One user has opened this observation. Per user, like replay's `SessionRecordingViewed`."""

    observation = models.ForeignKey("replay_vision.ReplayObservation", on_delete=models.CASCADE, related_name="views")
    # db_constraint=False: the migration policy blocks real FK constraints to the hot posthog_team/posthog_user tables.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["observation", "user"], name="unique_replay_observation_view_per_user"),
        ]
